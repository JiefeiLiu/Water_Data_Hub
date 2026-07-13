#!/usr/bin/env python3
"""Append aggregated Water Quality Portal result features to the public dataset.

By default, results are grouped into one column set per analyte: all sample
fractions (Dissolved, Total, Total Recoverable, ...) are merged, and numeric
values are unit-converted to a single target unit per analyte before they are
aggregated. This keeps each analyte in one well-populated set of columns instead
of fragmenting it across (characteristic, fraction, unit) variants.

Use --per-triple to fall back to the older behavior of one column set per
(CharacteristicName, ResultSampleFractionText, ResultMeasureUnitCode) triple.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import math
import re
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "public_data" / "report207appendixA_all_tables_labeled_acc_wqp_location_matches.csv"
DEFAULT_OUTPUT = REPO_ROOT / "public_data" / "report207appendixA_all_tables_labeled_acc_wqp_features.csv"
DEFAULT_MANIFEST = Path(__file__).resolve().parent / "outputs" / "public_data_wqp_feature_manifest.csv"

BASE_FEATURE_COLUMNS = [
    "wqp_feature_result_rows_used",
    "wqp_feature_activity_count",
    "wqp_feature_characteristic_count",
    "wqp_feature_numeric_characteristic_count",
    "wqp_feature_first_sample_date",
    "wqp_feature_last_sample_date",
]

STAT_NAMES = [
    "result_count",
    "activity_count",
    "numeric_count",
    "nondetect_count",
    "unconvertible_count",
    "mean",
    "min",
    "median",
    "max",
    "latest_value",
    "latest_date",
    "first_date",
    "last_date",
]


# --- Analyte canonicalization and unit conversion ----------------------------

# Normalized CharacteristicName -> (analyte slug, target unit). The target unit
# is the single unit every numeric value for that analyte is converted to before
# aggregation. An empty target unit means the analyte is unitless (e.g. pH).
ANALYTE_REGISTRY: dict[str, tuple[str, str]] = {
    "calcium": ("calcium", "mg/L"),
    "magnesium": ("magnesium", "mg/L"),
    "sodium": ("sodium", "mg/L"),
    "potassium": ("potassium", "mg/L"),
    "sodium plus potassium": ("sodium_plus_potassium", "mg/L"),
    "chloride": ("chloride", "mg/L"),
    "sulfate": ("sulfate", "mg/L"),
    "fluoride": ("fluoride", "mg/L"),
    "boron": ("boron", "mg/L"),
    "silica": ("silica", "mg/L"),
    "iron": ("iron", "mg/L"),
    "manganese": ("manganese", "mg/L"),
    "nitrate": ("nitrate", "mg/L"),
    "nitrite": ("nitrite", "mg/L"),
    "alkalinity": ("alkalinity", "mg/L"),
    "bicarbonate": ("bicarbonate", "mg/L"),
    "carbonate": ("carbonate", "mg/L"),
    "hardness": ("hardness", "mg/L"),
    "hardness, ca, mg": ("hardness", "mg/L"),
    "total dissolved solids": ("total_dissolved_solids", "mg/L"),
    "conductivity": ("conductivity", "uS/cm"),
    "specific conductance": ("specific_conductance", "uS/cm"),
    "salinity": ("salinity", "ppth"),
    "temperature": ("temperature_water", "deg C"),
    "temperature, water": ("temperature_water", "deg C"),
    "ph": ("ph", ""),
    "sodium adsorption ratio": ("sodium_adsorption_ratio", ""),
    "turbidity": ("turbidity", "NTU"),
}

# Equivalent weight (g/eq) for converting ueq/L and meq/L to mg/L.
EQUIVALENT_WEIGHT: dict[str, float] = {
    "calcium": 20.04,
    "magnesium": 12.152,
    "sodium": 22.990,
    "potassium": 39.098,
    "chloride": 35.453,
    "sulfate": 48.03,
    "bicarbonate": 61.017,
    "carbonate": 30.005,
    "fluoride": 18.998,
}


@dataclass(frozen=True)
class Classification:
    """How one result row maps onto a feature column group."""

    stem: str
    target_unit: str
    characteristic: str
    fraction: str
    unit: str
    raw_value: float | None
    converted_value: float | None


def normalize_unit(unit: str) -> str:
    return re.sub(r"\s+", " ", unit.strip().lower())


def resolve_analyte(characteristic: str) -> tuple[str, str] | None:
    return ANALYTE_REGISTRY.get(characteristic.strip().lower())


def convert_to_target(analyte_slug: str, target_unit: str, unit: str, value: float) -> float | None:
    """Convert ``value`` (in ``unit``) to ``target_unit``; None if not convertible."""
    u = normalize_unit(unit)
    if target_unit == "":  # unitless analytes such as pH or SAR
        return value
    if target_unit == "mg/L":
        if u in ("mg/l", "ppm", "mg/l as na", "mg/l as caco3", "mg/l as n", "mg/l as no3", "mg/kg"):
            return value
        if u in ("ug/l", "µg/l", "ppb"):
            return value * 0.001
        if u in ("g/l",):
            return value * 1000.0
        if u == "ueq/l":
            weight = EQUIVALENT_WEIGHT.get(analyte_slug)
            return value * weight / 1000.0 if weight else None
        if u == "meq/l":
            weight = EQUIVALENT_WEIGHT.get(analyte_slug)
            return value * weight if weight else None
        return None
    if target_unit == "uS/cm":
        if u in ("us/cm", "umho/cm", "umho", "umhos/cm", "us/cm @25c"):
            return value
        if u == "ms/cm":
            return value * 1000.0
        return None
    if target_unit == "ppth":
        if u in ("ppth", "ppt", "psu", "g/kg", "g/l", "o/oo"):
            return value
        return None
    if target_unit == "deg C":
        if u in ("deg c", "c", "degc"):
            return value
        if u in ("deg f", "f", "degf"):
            return (value - 32.0) * 5.0 / 9.0
        return None
    if target_unit == "NTU":
        if u in ("ntu", "fnu", "ntru", "jtu", ""):
            return value
        return None
    return None


def legacy_stem(characteristic: str, fraction: str, unit: str) -> str:
    parts = [characteristic]
    if fraction:
        parts.append(fraction)
    if unit:
        parts.append(unit)
    slug = slugify("_".join(parts))
    digest = hashlib.sha1("||".join((characteristic, fraction, unit)).encode("utf-8")).hexdigest()[:8]
    return f"wqp_{slug}_{digest}"


def merged_stem(analyte_slug: str, target_unit: str) -> str:
    unit_slug = slugify(target_unit) if target_unit else ""
    return f"wqp_{analyte_slug}_{unit_slug}" if unit_slug else f"wqp_{analyte_slug}"


def classify_result(row: dict[str, str], merge: bool) -> Classification | None:
    characteristic = (row.get("CharacteristicName") or "").strip()
    if not characteristic:
        return None
    fraction = (row.get("ResultSampleFractionText") or "").strip()
    unit = (row.get("ResultMeasure/MeasureUnitCode") or "").strip()
    raw_value = parse_numeric_result(row.get("ResultMeasureValue") or "")

    if not merge:
        return Classification(
            stem=legacy_stem(characteristic, fraction, unit),
            target_unit=unit,
            characteristic=characteristic,
            fraction=fraction,
            unit=unit,
            raw_value=raw_value,
            converted_value=raw_value,
        )

    spec = resolve_analyte(characteristic)
    if spec is None:
        # Unknown analyte: merge fractions but keep the unit so we never mix
        # incompatible units we have no conversion rule for.
        analyte_slug = f"other_{slugify(characteristic)}"
        target_unit = unit
        stem = f"wqp_{analyte_slug}_{slugify(unit) or 'none'}"
        converted = raw_value
    else:
        analyte_slug, target_unit = spec
        stem = merged_stem(analyte_slug, target_unit)
        converted = (
            convert_to_target(analyte_slug, target_unit, unit, raw_value)
            if raw_value is not None
            else None
        )
    return Classification(
        stem=stem,
        target_unit=target_unit,
        characteristic=characteristic,
        fraction=fraction,
        unit=unit,
        raw_value=raw_value,
        converted_value=converted,
    )


# --- Aggregation -------------------------------------------------------------


@dataclass
class CharacteristicAgg:
    target_unit: str = ""
    source_characteristics: set[str] = field(default_factory=set)
    source_fractions: set[str] = field(default_factory=set)
    source_units: set[str] = field(default_factory=set)
    result_count: int = 0
    unconvertible_count: int = 0
    numeric_values: list[float] = field(default_factory=list)
    activity_ids: set[str] = field(default_factory=set)
    detection_condition_counts: Counter[str] = field(default_factory=Counter)
    first_date: str = ""
    last_date: str = ""
    latest_value: float | None = None
    latest_date: str = ""

    def add(self, row: dict[str, str], classification: Classification) -> None:
        self.result_count += 1
        self.target_unit = classification.target_unit
        self.source_characteristics.add(classification.characteristic)
        if classification.fraction:
            self.source_fractions.add(classification.fraction)
        self.source_units.add(classification.unit or "(none)")

        activity_id = (row.get("ActivityIdentifier") or "").strip()
        if activity_id:
            self.activity_ids.add(activity_id)

        sample_date = normalize_date(row.get("ActivityStartDate") or "")
        if sample_date:
            if not self.first_date or sample_date < self.first_date:
                self.first_date = sample_date
            if not self.last_date or sample_date > self.last_date:
                self.last_date = sample_date

        detection_condition = (row.get("ResultDetectionConditionText") or "").strip()
        if detection_condition:
            self.detection_condition_counts[detection_condition] += 1

        if classification.converted_value is None:
            # A numeric value was present but its unit could not be converted to
            # the analyte's target unit, so it is excluded from numeric stats.
            if classification.raw_value is not None:
                self.unconvertible_count += 1
            return
        value = classification.converted_value
        self.numeric_values.append(value)
        if sample_date and (not self.latest_date or sample_date >= self.latest_date):
            self.latest_date = sample_date
            self.latest_value = value

    def summary(self) -> dict[str, str]:
        values = self.numeric_values
        output = {
            "result_count": str(self.result_count),
            "activity_count": str(len(self.activity_ids)),
            "numeric_count": str(len(values)),
            "nondetect_count": str(sum(self.detection_condition_counts.values())),
            "unconvertible_count": str(self.unconvertible_count),
            "first_date": self.first_date,
            "last_date": self.last_date,
        }
        if values:
            sorted_values = sorted(values)
            output.update(
                {
                    "mean": format_float(sum(values) / len(values)),
                    "min": format_float(sorted_values[0]),
                    "median": format_float(median(sorted_values)),
                    "max": format_float(sorted_values[-1]),
                    "latest_value": format_float(self.latest_value) if self.latest_value is not None else "",
                    "latest_date": self.latest_date,
                }
            )
        else:
            output.update(
                {"mean": "", "min": "", "median": "", "max": "", "latest_value": "", "latest_date": ""}
            )
        return output

    def merge(self, other: "CharacteristicAgg") -> None:
        self.target_unit = self.target_unit or other.target_unit
        self.source_characteristics.update(other.source_characteristics)
        self.source_fractions.update(other.source_fractions)
        self.source_units.update(other.source_units)
        self.result_count += other.result_count
        self.unconvertible_count += other.unconvertible_count
        self.numeric_values.extend(other.numeric_values)
        self.activity_ids.update(other.activity_ids)
        self.detection_condition_counts.update(other.detection_condition_counts)
        if other.first_date and (not self.first_date or other.first_date < self.first_date):
            self.first_date = other.first_date
        if other.last_date and (not self.last_date or other.last_date > self.last_date):
            self.last_date = other.last_date
        if other.latest_date and (not self.latest_date or other.latest_date >= self.latest_date):
            self.latest_date = other.latest_date
            self.latest_value = other.latest_value


@dataclass
class StationAgg:
    merge_analytes: bool = True
    characteristics: dict[str, CharacteristicAgg] = field(default_factory=dict)
    result_rows: int = 0
    activity_ids: set[str] = field(default_factory=set)
    first_date: str = ""
    last_date: str = ""

    def add(self, row: dict[str, str]) -> None:
        classification = classify_result(row, self.merge_analytes)
        if classification is None:
            return

        self.result_rows += 1
        activity_id = (row.get("ActivityIdentifier") or "").strip()
        if activity_id:
            self.activity_ids.add(activity_id)
        sample_date = normalize_date(row.get("ActivityStartDate") or "")
        if sample_date:
            if not self.first_date or sample_date < self.first_date:
                self.first_date = sample_date
            if not self.last_date or sample_date > self.last_date:
                self.last_date = sample_date

        agg = self.characteristics.setdefault(classification.stem, CharacteristicAgg())
        agg.add(row, classification)

    def merge(self, other: "StationAgg") -> None:
        self.result_rows += other.result_rows
        self.activity_ids.update(other.activity_ids)
        if other.first_date and (not self.first_date or other.first_date < self.first_date):
            self.first_date = other.first_date
        if other.last_date and (not self.last_date or other.last_date > self.last_date):
            self.last_date = other.last_date
        for stem, other_agg in other.characteristics.items():
            self.characteristics.setdefault(stem, CharacteristicAgg()).merge(other_agg)


def parse_numeric_result(value: str) -> float | None:
    value = value.strip().replace(",", "")
    if not value:
        return None
    value = re.sub(r"^[<>~= ]+", "", value)
    match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?", value)
    if not match:
        return None
    try:
        number = float(match.group(0))
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def normalize_date(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(value[:10], fmt).date().isoformat()
        except ValueError:
            pass
    return value[:10]


def median(sorted_values: list[float]) -> float:
    midpoint = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return sorted_values[midpoint]
    return (sorted_values[midpoint - 1] + sorted_values[midpoint]) / 2.0


def format_float(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.10g}"


def slugify(value: str) -> str:
    value = value.lower()
    value = value.replace("%", " percent ")
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "unknown"


def csv_member_name(zip_file: zipfile.ZipFile) -> str:
    members = [name for name in zip_file.namelist() if name.lower().endswith(".csv")]
    if not members:
        raise FileNotFoundError("zip file contains no CSV member")
    return members[0]


def iter_zip_csv_rows(path: Path):
    with zipfile.ZipFile(path) as zip_file:
        member = csv_member_name(zip_file)
        with zip_file.open(member) as raw_handle:
            text_handle = io.TextIOWrapper(raw_handle, encoding="utf-8-sig", errors="replace", newline="")
            yield from csv.DictReader(text_handle)


def read_input_rows(input_path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with input_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{input_path} has no header row")
        return list(reader), reader.fieldnames


def split_paths(value: str) -> list[Path]:
    return [Path(item.strip()) for item in value.split(";") if item.strip()]


def split_ids(value: str) -> list[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


def row_station_refs(row: dict[str, str], aggregate_nearby: bool) -> tuple[list[Path], list[str]]:
    """Return the (result zips, station ids) a row aggregates features from."""
    if aggregate_nearby:
        zips = split_paths(row.get("wqp_nearby_result_zips") or "")
        station_ids = split_ids(row.get("wqp_nearby_station_ids") or "")
    else:
        zips = split_paths(row.get("wqp_result_zip") or "")
        station_id = (row.get("wqp_monitoring_location_identifier") or "").strip()
        station_ids = [station_id] if station_id else []
    return zips, station_ids


def wanted_station_sources(rows: list[dict[str, str]], aggregate_nearby: bool) -> dict[Path, set[str]]:
    wanted: dict[Path, set[str]] = defaultdict(set)
    for row in rows:
        if row.get("wqp_match_status") != "matched":
            continue
        zips, station_ids = row_station_refs(row, aggregate_nearby)
        if not station_ids:
            continue
        for result_zip in zips:
            wanted[result_zip].update(station_ids)
    return wanted


def collect_station_features(
    wanted: dict[Path, set[str]], merge_analytes: bool
) -> dict[tuple[Path, str], StationAgg]:
    features: dict[tuple[Path, str], StationAgg] = {}
    for index, (zip_path, station_ids) in enumerate(sorted(wanted.items()), start=1):
        print(f"[{index}/{len(wanted)}] Scanning {zip_path.name} for {len(station_ids)} matched station(s)", flush=True)
        for station_id in station_ids:
            features[(zip_path, station_id)] = StationAgg(merge_analytes=merge_analytes)
        for row in iter_zip_csv_rows(zip_path):
            station_id = (row.get("MonitoringLocationIdentifier") or "").strip()
            if station_id not in station_ids:
                continue
            features[(zip_path, station_id)].add(row)
    return features


@dataclass
class GroupMeta:
    target_unit: str = ""
    source_characteristics: set[str] = field(default_factory=set)
    source_fractions: set[str] = field(default_factory=set)
    source_units: set[str] = field(default_factory=set)


def all_feature_groups(features: dict[tuple[Path, str], StationAgg]) -> dict[str, GroupMeta]:
    groups: dict[str, GroupMeta] = {}
    for station_features in features.values():
        for stem, agg in station_features.characteristics.items():
            meta = groups.setdefault(stem, GroupMeta())
            meta.target_unit = meta.target_unit or agg.target_unit
            meta.source_characteristics.update(agg.source_characteristics)
            meta.source_fractions.update(agg.source_fractions)
            meta.source_units.update(agg.source_units)
    return groups


def make_feature_columns(stems: list[str]) -> list[str]:
    columns: list[str] = []
    for stem in stems:
        columns.extend(f"{stem}_{stat}" for stat in STAT_NAMES)
    return columns


def station_base_features(station_features: StationAgg | None) -> dict[str, str]:
    if station_features is None:
        return {column: "" for column in BASE_FEATURE_COLUMNS}
    numeric_characteristics = sum(1 for agg in station_features.characteristics.values() if agg.numeric_values)
    return {
        "wqp_feature_result_rows_used": str(station_features.result_rows),
        "wqp_feature_activity_count": str(len(station_features.activity_ids)),
        "wqp_feature_characteristic_count": str(len(station_features.characteristics)),
        "wqp_feature_numeric_characteristic_count": str(numeric_characteristics),
        "wqp_feature_first_sample_date": station_features.first_date,
        "wqp_feature_last_sample_date": station_features.last_date,
    }


def merged_station_features(
    zip_paths: list[Path],
    station_ids: list[str],
    features: dict[tuple[Path, str], StationAgg],
) -> StationAgg | None:
    merged: StationAgg | None = None
    for zip_path in zip_paths:
        for station_id in station_ids:
            station_features = features.get((zip_path, station_id))
            if station_features is None:
                continue
            if merged is None:
                merged = StationAgg()
            merged.merge(station_features)
    return merged


def row_feature_values(
    row: dict[str, str],
    features: dict[tuple[Path, str], StationAgg],
    feature_columns: list[str],
    aggregate_nearby: bool,
) -> dict[str, str]:
    result = {column: "" for column in feature_columns}
    if row.get("wqp_match_status") != "matched":
        return {**station_base_features(None), **result}

    zip_paths, station_ids = row_station_refs(row, aggregate_nearby)
    station_features = merged_station_features(zip_paths, station_ids, features)
    output = station_base_features(station_features)
    if station_features is None:
        return {**output, **result}

    for stem, agg in station_features.characteristics.items():
        for stat_name, value in agg.summary().items():
            column = f"{stem}_{stat_name}"
            if column in result:
                result[column] = value
    return {**output, **result}


def write_feature_manifest(manifest_path: Path, stems: list[str], groups: dict[str, GroupMeta]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "feature_stem",
                "target_unit",
                "source_characteristics",
                "merged_fractions",
                "source_units",
            ],
        )
        writer.writeheader()
        for stem in stems:
            meta = groups[stem]
            writer.writerow(
                {
                    "feature_stem": stem,
                    "target_unit": meta.target_unit,
                    "source_characteristics": "; ".join(sorted(meta.source_characteristics)),
                    "merged_fractions": "; ".join(sorted(meta.source_fractions)),
                    "source_units": "; ".join(sorted(meta.source_units)),
                }
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="WQP location-match CSV")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output CSV with WQP feature columns")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="Feature-name manifest CSV")
    parser.add_argument(
        "--per-triple",
        action="store_true",
        help="Legacy mode: one column set per (characteristic, fraction, unit) triple with no unit conversion",
    )
    parser.add_argument(
        "--aggregate-nearby",
        action="store_true",
        help=(
            "Aggregate results from every WQP station within the match radius (wqp_nearby_* columns) instead of "
            "only the single matched station, so physical and chemical features are pooled across nearby stations"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    merge_analytes = not args.per_triple
    rows, input_fields = read_input_rows(args.input)
    wanted = wanted_station_sources(rows, args.aggregate_nearby)
    print(f"Loaded {len(rows)} input rows; {sum(len(v) for v in wanted.values())} station/source pairs requested", flush=True)
    if args.aggregate_nearby:
        print("Aggregating features across all WQP stations within the match radius", flush=True)
    features = collect_station_features(wanted, merge_analytes)
    groups = all_feature_groups(features)
    stems = sorted(groups)
    feature_columns = make_feature_columns(stems)
    write_feature_manifest(args.manifest, stems, groups)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[*input_fields, *BASE_FEATURE_COLUMNS, *feature_columns])
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, **row_feature_values(row, features, feature_columns, args.aggregate_nearby)})

    matched_rows = sum(1 for row in rows if row.get("wqp_match_status") == "matched")
    print(f"Wrote {len(rows)} rows to {args.output}", flush=True)
    print(f"Matched rows with WQP features: {matched_rows}", flush=True)
    print(f"Feature groups ({'analyte' if merge_analytes else 'characteristic/fraction/unit'}): {len(stems)}", flush=True)
    print(f"Added WQP feature columns: {len(BASE_FEATURE_COLUMNS) + len(feature_columns)}", flush=True)
    print(f"Feature manifest: {args.manifest}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build a per-plant water-quality statistics dataset for manual checking.

Reads the WQP features table (built with a recency window, default 30 years) and
writes one row per sample plant: key facility fields plus, for each analyte, the
median / mean / min / max / sample count / year range. It is a trimmed,
human-readable view of the water-quality statistics behind the LLM prompts.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "public_data" / "processed_data" / "report207appendixA_all_tables_labeled_acc_wqp_features.csv"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "outputs" / "water_quality_stats_30yr_per_plant.csv"

FACILITY_COLUMNS = [
    "SOURCE EXCEL ROW", "NAME", "OWNER", "CITY", "STATE", "COUNTY",
    "TYPE", "PURPOSE", "WATER SOURCE", "MGD MAX",
    "RAW WATER TDS OR CONDUCTIVITY", "DISPOSAL CONCENTRATE", "ACC_X", "ACC_Y",
]
MATCH_COLUMNS = [
    "wqp_match_status", "wqp_match_method", "wqp_match_distance_km",
    "wqp_nearby_station_count", "wqp_feature_first_sample_date", "wqp_feature_last_sample_date",
]

# analyte feature stem -> short, self-documenting label (unit kept in the name).
ANALYTES = [
    ("wqp_total_dissolved_solids_mg_l", "tds_mg_l"),
    ("wqp_specific_conductance_us_cm", "spec_conductance_us_cm"),
    ("wqp_salinity_ppth", "salinity_ppth"),
    ("wqp_conductivity_us_cm", "conductivity_us_cm"),
    ("wqp_calcium_mg_l", "calcium_mg_l"),
    ("wqp_magnesium_mg_l", "magnesium_mg_l"),
    ("wqp_sodium_mg_l", "sodium_mg_l"),
    ("wqp_potassium_mg_l", "potassium_mg_l"),
    ("wqp_ph", "ph"),
    ("wqp_temperature_water_deg_c", "temperature_deg_c"),
    ("wqp_turbidity_ntu", "turbidity_ntu"),
]
STATS = ["median", "mean", "min", "max"]


def year(value: str) -> str:
    value = (value or "").strip()
    return value[:4] if len(value) >= 4 else ""


def year_range(first: str, last: str) -> str:
    f, l = year(first), year(last)
    if f and l:
        return f"{f}-{l}"
    return f or l


def build(input_path: Path, output_path: Path) -> tuple[int, int]:
    with input_path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"{input_path} has no data rows")
    present = {stem for stem, _ in ANALYTES if f"{stem}_median" in rows[0]}
    analytes = [(stem, label) for stem, label in ANALYTES if stem in present]

    fieldnames = [*FACILITY_COLUMNS, *MATCH_COLUMNS]
    for _, label in analytes:
        fieldnames.extend(f"{label}_{stat}" for stat in STATS)
        fieldnames.append(f"{label}_n")
        fieldnames.append(f"{label}_years")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            out = {column: row.get(column, "") for column in FACILITY_COLUMNS + MATCH_COLUMNS}
            for stem, label in analytes:
                for stat in STATS:
                    out[f"{label}_{stat}"] = row.get(f"{stem}_{stat}", "")
                out[f"{label}_n"] = row.get(f"{stem}_result_count", "")
                out[f"{label}_years"] = year_range(row.get(f"{stem}_first_date", ""), row.get(f"{stem}_last_date", ""))
            writer.writerow(out)
    return len(rows), len(analytes)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="WQP features CSV (built with the desired recency window)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Per-plant statistics CSV")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    plants, analytes = build(args.input, args.output)
    print(f"Wrote {plants} plant rows x {analytes} analytes to {args.output}")


if __name__ == "__main__":
    main()

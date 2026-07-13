#!/usr/bin/env python3
"""Match public dataset coordinates to Water Quality Portal monitoring locations."""

from __future__ import annotations

import argparse
import csv
import io
import math
import re
import urllib.parse
import urllib.request
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WATER_DATA_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = REPO_ROOT / "public_data" / "report207appendixA_all_tables_labeled_acc.csv"
DEFAULT_OUTPUT = REPO_ROOT / "public_data" / "report207appendixA_all_tables_labeled_acc_wqp_location_matches.csv"
DEFAULT_RESULT_DIR = WATER_DATA_DIR / "wqp_result_zips"
DEFAULT_STATION_DIR = WATER_DATA_DIR / "wqp_station_zips"

WQP_STATION_SEARCH_URL = "https://www.waterqualitydata.us/data/Station/search"
USER_AGENT = "Water-Hub-WQP-matcher/1.0"
CHUNK_SIZE = 1024 * 1024

DEFAULT_SAMPLE_MEDIA = ["water", "Water"]
DEFAULT_CHARACTERISTIC_TYPES = ["Inorganics, Major, Metals", "Physical"]
DEFAULT_PROVIDERS = ["NWIS", "STEWARDS", "STORET"]
DEFAULT_CHARACTERISTIC_NAMES_BY_TYPE = {
    "Inorganics, Major, Metals": [
        "Alkalinity",
        "Alkalinity, total",
        "Bicarbonate",
        "Boron",
        "Calcium",
        "Carbonate",
        "Chloride",
        "Fluoride",
        "Hardness, Ca, Mg",
        "Iron",
        "Magnesium",
        "Manganese",
        "Nitrate",
        "Nitrite",
        "Potassium",
        "Silica",
        "Sodium",
        "Sodium adsorption ratio [(Na)/(sq root of 1/2 Ca + Mg)]",
        "Sodium plus potassium",
        "Sulfate",
    ],
    "Physical": [
        "Conductivity",
        "pH",
        "Salinity",
        "Specific conductance",
        "Temperature",
        "Temperature, water",
        "Total dissolved solids",
        "Turbidity",
    ],
}
DEFAULT_INCLUDE_LEGACY_RESULT_ZIPS = False

# Characteristic group(s) whose stations carry the major-ion chemistry a
# desalination expert cares about (calcium, magnesium, sodium, potassium, ...).
# Analyte-prioritized matching prefers the nearest station from one of these
# groups over a closer physical-only station that lacks that chemistry.
DEFAULT_PRIORITY_CHARACTERISTIC_TYPES = ["Inorganics, Major, Metals"]

MATCH_COLUMNS = [
    "wqp_match_status",
    "wqp_match_method",
    "wqp_match_distance_km",
    "wqp_monitoring_location_identifier",
    "wqp_monitoring_location_name",
    "wqp_monitoring_location_type",
    "wqp_provider_name",
    "wqp_county_code",
    "wqp_result_zip",
    "wqp_station_zip",
    "wqp_station_longitude",
    "wqp_station_latitude",
    "wqp_result_rows_at_station",
    "wqp_activity_count_at_station",
    "wqp_nearby_station_count",
    "wqp_nearby_min_distance_km",
    "wqp_nearby_station_ids",
    "wqp_nearby_result_zips",
    "wqp_match_note",
]

COUNTY_KEY_ALIASES = {
    ("CA", "santamonica"): ["losangeles"],
    ("TX", "hildalgo"): ["hidalgo"],
}

INFERRED_COUNTY_KEY_BY_SOURCE_ROW = {
    ("CO", "92"): "logan",
    ("CO", "95"): "adams",
    ("CO", "102"): "arapahoe",
    ("NC", "88"): "dare",
    ("NC", "104"): "onslow",
    ("NC", "111"): "onslow",
    ("NC", "113"): "hyde",
    ("NC", "116"): "tyrrell",
    ("TX", "63"): "taylor",
    ("TX", "68"): "nolan",
    ("UT", "108"): "saltlake",
}


@dataclass(frozen=True)
class WqpSource:
    state: str
    county_key: str
    location_code: str
    result_zip_path: Path
    station_zip_path: Path
    station_url: str
    characteristic_type: str
    characteristic_names: tuple[str, ...]
    label: str


@dataclass(frozen=True)
class Station:
    identifier: str
    name: str
    location_type: str
    provider: str
    county_code: str
    latitude: float
    longitude: float
    source: WqpSource


@dataclass
class PointRow:
    index: int
    latitude: float
    longitude: float
    group_key: tuple[Path, ...]


@dataclass
class MatchResult:
    status: str
    method: str
    distance_km: str = ""
    monitoring_location_identifier: str = ""
    monitoring_location_name: str = ""
    monitoring_location_type: str = ""
    provider_name: str = ""
    county_code: str = ""
    result_zip: str = ""
    station_zip: str = ""
    longitude: str = ""
    latitude: str = ""
    result_rows_at_station: str = ""
    activity_count_at_station: str = ""
    nearby_station_count: str = ""
    nearby_min_distance_km: str = ""
    nearby_station_ids: str = ""
    nearby_result_zips: str = ""
    note: str = ""

    def as_row(self) -> dict[str, str]:
        return {
            "wqp_match_status": self.status,
            "wqp_match_method": self.method,
            "wqp_match_distance_km": self.distance_km,
            "wqp_monitoring_location_identifier": self.monitoring_location_identifier,
            "wqp_monitoring_location_name": self.monitoring_location_name,
            "wqp_monitoring_location_type": self.monitoring_location_type,
            "wqp_provider_name": self.provider_name,
            "wqp_county_code": self.county_code,
            "wqp_result_zip": self.result_zip,
            "wqp_station_zip": self.station_zip,
            "wqp_station_longitude": self.longitude,
            "wqp_station_latitude": self.latitude,
            "wqp_result_rows_at_station": self.result_rows_at_station,
            "wqp_activity_count_at_station": self.activity_count_at_station,
            "wqp_nearby_station_count": self.nearby_station_count,
            "wqp_nearby_min_distance_km": self.nearby_min_distance_km,
            "wqp_nearby_station_ids": self.nearby_station_ids,
            "wqp_nearby_result_zips": self.nearby_result_zips,
            "wqp_match_note": self.note,
        }


def normalize_name(value: str) -> str:
    value = value.lower().replace("saint", "st")
    value = re.sub(r"\b(county|parish|borough|city and borough|municipality|census area)\b", "", value)
    return re.sub(r"[^a-z0-9]", "", value)


def county_tokens(raw_county: str) -> list[str]:
    county = (raw_county or "").strip()
    if not county or county.lower() == "none":
        return ["none"]
    return [part.strip() for part in re.split(r"\s*(?:&|/|;|\band\b)\s*", county, flags=re.IGNORECASE) if part.strip()]


def search_keys(state: str, county: str) -> list[tuple[str, str]]:
    state = state.strip().upper()
    keys = []
    for county_token in county_tokens(county):
        county_key = "none" if county_token.lower() == "none" else normalize_name(county_token)
        keys.append((state, county_key))
    return keys


def candidate_search_keys(row: dict[str, str]) -> list[tuple[str, str]]:
    keys = search_keys(row.get("STATE", ""), row.get("COUNTY", ""))
    state = (row.get("STATE") or "").strip().upper()
    source_row = (row.get("SOURCE EXCEL ROW") or "").strip()
    inferred_key = INFERRED_COUNTY_KEY_BY_SOURCE_ROW.get((state, source_row))
    if inferred_key:
        keys.append((state, inferred_key))
    for key in list(keys):
        for alias in COUNTY_KEY_ALIASES.get(key, []):
            keys.append((key[0], alias))

    deduped = []
    seen = set()
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def parse_float(value: str) -> float | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def encode_semicolon_values(values: list[str]) -> str:
    return ";".join(values)


def make_station_url(
    location_code: str,
    sample_media: list[str],
    characteristic_types: list[str],
    characteristic_names: list[str],
    providers: list[str],
) -> str:
    location_param = "countycode" if location_code.count(":") == 2 else "statecode"
    params = {
        location_param: location_code,
        "sampleMedia": encode_semicolon_values(sample_media),
        "characteristicType": encode_semicolon_values(characteristic_types),
        "providers": encode_semicolon_values(providers),
        "mimeType": "csv",
        "zip": "yes",
        "sorted": "no",
    }
    if characteristic_names:
        params["characteristicName"] = encode_semicolon_values(characteristic_names)
    return f"{WQP_STATION_SEARCH_URL}?{urllib.parse.urlencode(params)}"


def parse_multi_value(value: str | None, default: list[str]) -> list[str]:
    if value is None:
        return default
    values = [item.strip() for item in value.split(";") if item.strip()]
    return values or default


def parse_optional_multi_value(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [item.strip() for item in value.split(";") if item.strip()]


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "all"


def station_zip_path_for(result_zip_path: Path, result_dir: Path, station_dir: Path) -> Path:
    relative = result_zip_path.relative_to(result_dir)
    filename = relative.name.replace("_wqp_results.zip", "_wqp_stations.zip")
    return station_dir / relative.parent / filename


def discover_sources(
    result_dir: Path,
    station_dir: Path,
    sample_media: list[str],
    characteristic_types: list[str],
    characteristic_names_override: list[str] | None,
    providers: list[str],
    include_legacy_result_zips: bool = DEFAULT_INCLUDE_LEGACY_RESULT_ZIPS,
) -> list[WqpSource]:
    sources: list[WqpSource] = []
    characteristic_type_by_slug = {slugify(value): value for value in DEFAULT_CHARACTERISTIC_TYPES}
    pattern = re.compile(r"^([A-Z]{2})_(.+)_US_(\d{2})(?:_(\d{3}))?(?:_([a-z0-9_]+))?_wqp_results\.zip$")
    for result_zip_path in sorted(result_dir.glob("*/*_wqp_results.zip")):
        match = pattern.match(result_zip_path.name)
        if not match:
            continue
        state, slug, state_fips, county_fips, characteristic_slug = match.groups()
        if county_fips:
            county_slug = re.sub(r"_county$", "", slug)
            county_key = normalize_name(county_slug)
            location_code = f"US:{state_fips}:{county_fips}"
        else:
            county_key = "none"
            location_code = f"US:{state_fips}"
        characteristic_type = characteristic_type_by_slug.get(characteristic_slug or "")
        if not characteristic_type and not include_legacy_result_zips:
            continue
        source_characteristic_types = [characteristic_type] if characteristic_type else characteristic_types
        source_characteristic_names = (
            characteristic_names_override
            if characteristic_names_override is not None
            else DEFAULT_CHARACTERISTIC_NAMES_BY_TYPE.get(characteristic_type or "", [])
        )
        station_zip_path = station_zip_path_for(result_zip_path, result_dir, station_dir)
        sources.append(
            WqpSource(
                state=state,
                county_key=county_key,
                location_code=location_code,
                result_zip_path=result_zip_path,
                station_zip_path=station_zip_path,
                station_url=make_station_url(
                    location_code,
                    sample_media,
                    source_characteristic_types,
                    source_characteristic_names,
                    providers,
                ),
                characteristic_type=characteristic_type or encode_semicolon_values(characteristic_types),
                characteristic_names=tuple(source_characteristic_names),
                label=result_zip_path.stem,
            )
        )
    return sources


def index_sources(sources: list[WqpSource]) -> tuple[dict[tuple[str, str], list[WqpSource]], dict[str, list[WqpSource]]]:
    by_county: dict[tuple[str, str], list[WqpSource]] = defaultdict(list)
    statewide: dict[str, list[WqpSource]] = defaultdict(list)
    for source in sources:
        if source.county_key == "none":
            statewide[source.state].append(source)
        else:
            by_county[(source.state, source.county_key)].append(source)
    return by_county, statewide


def ensure_station_zip(source: WqpSource, replace: bool, timeout: int) -> str:
    if source.station_zip_path.exists() and not replace:
        return "skipped_existing"

    source.station_zip_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = source.station_zip_path.with_suffix(source.station_zip_path.suffix + ".part")
    request = urllib.request.Request(source.station_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response, temp_path.open("wb") as handle:
        while True:
            chunk = response.read(CHUNK_SIZE)
            if not chunk:
                break
            handle.write(chunk)
    temp_path.replace(source.station_zip_path)
    return "downloaded"


def ensure_station_zips(sources: list[WqpSource], replace: bool, timeout: int, skip_download: bool) -> None:
    for index, source in enumerate(sources, start=1):
        if skip_download:
            if not source.station_zip_path.exists():
                print(f"[{index}/{len(sources)}] Missing station zip: {source.station_zip_path}", flush=True)
            continue
        print(f"[{index}/{len(sources)}] Station metadata {source.location_code}", flush=True)
        try:
            status = ensure_station_zip(source, replace=replace, timeout=timeout)
        except Exception as exc:
            status = f"failed: {exc}"
        print(f"  {status}: {source.station_zip_path}", flush=True)


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


def read_stations(source: WqpSource) -> list[Station]:
    if not source.station_zip_path.exists():
        return []

    stations: list[Station] = []
    seen: set[str] = set()
    for row in iter_zip_csv_rows(source.station_zip_path):
        identifier = (row.get("MonitoringLocationIdentifier") or "").strip()
        if not identifier or identifier in seen:
            continue
        lat = parse_float(row.get("LatitudeMeasure", ""))
        lon = parse_float(row.get("LongitudeMeasure", ""))
        if lat is None or lon is None:
            continue
        seen.add(identifier)
        stations.append(
            Station(
                identifier=identifier,
                name=(row.get("MonitoringLocationName") or "").strip(),
                location_type=(row.get("MonitoringLocationTypeName") or "").strip(),
                provider=(row.get("ProviderName") or row.get("OrganizationIdentifier") or "").strip(),
                county_code=(row.get("CountyCode") or "").strip(),
                latitude=lat,
                longitude=lon,
                source=source,
            )
        )
    return stations


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    radius_km = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius_km * math.asin(math.sqrt(a))


def join_paths(paths: list[Path]) -> str:
    return ";".join(str(path) for path in sorted(paths))


def source_paths_for_station(station: Station, sources: list[WqpSource]) -> tuple[str, str]:
    if not sources:
        sources = [station.source]
    return (
        join_paths([source.result_zip_path for source in sources]),
        join_paths([source.station_zip_path for source in sources]),
    )


def format_match(
    station: Station,
    sources: list[WqpSource],
    distance_km: float,
    method: str,
    note: str,
) -> MatchResult:
    result_zips, station_zips = source_paths_for_station(station, sources)
    return MatchResult(
        status="matched",
        method=method,
        distance_km=f"{distance_km:.6f}",
        monitoring_location_identifier=station.identifier,
        monitoring_location_name=station.name,
        monitoring_location_type=station.location_type,
        provider_name=station.provider,
        county_code=station.county_code,
        result_zip=result_zips,
        station_zip=station_zips,
        longitude=f"{station.longitude:.8f}",
        latitude=f"{station.latitude:.8f}",
        note=note,
    )


def match_group(
    points: list[PointRow],
    sources: list[WqpSource],
    max_nearest_km: float,
    priority_types: set[str],
) -> dict[int, MatchResult]:
    station_by_id: dict[str, Station] = {}
    sources_by_station_id: dict[str, list[WqpSource]] = defaultdict(list)
    for source in sources:
        for station in read_stations(source):
            station_by_id.setdefault(station.identifier, station)
            sources_by_station_id[station.identifier].append(source)

    # A station carries priority analytes (major-ion chemistry) if it was
    # returned by a priority characteristic-group station search.
    priority_station_ids = {
        identifier
        for identifier, station_sources in sources_by_station_id.items()
        if any(source.characteristic_type in priority_types for source in station_sources)
    }

    # All result zips for this group's candidate sources. Radius aggregation
    # scans these and keeps any row whose station is in a point's nearby set, so
    # both physical and major-ion result zips are covered.
    group_result_zips = join_paths([source.result_zip_path for source in sources])

    stations = list(station_by_id.values())
    results: dict[int, MatchResult] = {}
    if not stations:
        for point in points:
            results[point.index] = MatchResult(
                status="no_match",
                method="no_candidate_wqp_stations",
                note="no station metadata rows were available for candidate WQP result zips",
            )
        return results

    for point in points:
        nearest: tuple[float, Station] | None = None
        nearest_priority: tuple[float, Station] | None = None
        within_radius: list[tuple[float, Station]] = []
        for station in stations:
            distance_km = haversine_km(point.longitude, point.latitude, station.longitude, station.latitude)
            if nearest is None or distance_km < nearest[0]:
                nearest = (distance_km, station)
            if station.identifier in priority_station_ids and (
                nearest_priority is None or distance_km < nearest_priority[0]
            ):
                nearest_priority = (distance_km, station)
            if distance_km <= max_nearest_km:
                within_radius.append((distance_km, station))
        if nearest is None:
            results[point.index] = MatchResult(status="no_match", method="no_candidate_wqp_stations")
            continue

        # Prefer the nearest station that actually measures the priority analytes,
        # as long as it is within range; otherwise fall back to the nearest station
        # of any kind so physical-only coverage is not lost.
        if nearest_priority is not None and nearest_priority[0] <= max_nearest_km:
            distance_km, station = nearest_priority
            note = f"nearest WQP station with priority analytes within {max_nearest_km:g} km"
            if nearest[0] < distance_km - 1e-9:
                note += (
                    f"; closer station {nearest[1].identifier} at {nearest[0]:.2f} km"
                    " lacks the priority analytes"
                )
            station_sources = sources_by_station_id.get(station.identifier, [station.source])
            result = format_match(station, station_sources, distance_km, "nearest_priority_station", note)
        else:
            distance_km, station = nearest
            station_sources = sources_by_station_id.get(station.identifier, [station.source])
            if distance_km <= max_nearest_km:
                result = format_match(
                    station,
                    station_sources,
                    distance_km,
                    "nearest_station",
                    f"nearest WQP monitoring location within {max_nearest_km:g} km; no station with priority analytes in range",
                )
            else:
                result_zips, station_zips = source_paths_for_station(station, station_sources)
                result = MatchResult(
                    status="no_match",
                    method="nearest_station_too_far",
                    distance_km=f"{distance_km:.6f}",
                    monitoring_location_identifier=station.identifier,
                    monitoring_location_name=station.name,
                    monitoring_location_type=station.location_type,
                    provider_name=station.provider,
                    county_code=station.county_code,
                    result_zip=result_zips,
                    station_zip=station_zips,
                    longitude=f"{station.longitude:.8f}",
                    latitude=f"{station.latitude:.8f}",
                    note=f"nearest WQP monitoring location is farther than max distance {max_nearest_km:g} km",
                )

        # Record every station within the radius for optional neighborhood
        # aggregation in the feature builder.
        if within_radius:
            nearby_ids = sorted({station.identifier for _, station in within_radius})
            result.nearby_station_count = str(len(nearby_ids))
            result.nearby_min_distance_km = f"{min(distance for distance, _ in within_radius):.6f}"
            result.nearby_station_ids = ";".join(nearby_ids)
            result.nearby_result_zips = group_result_zips
        results[point.index] = result
    return results


def split_paths(value: str) -> list[Path]:
    return [Path(item.strip()) for item in value.split(";") if item.strip()]


def add_result_counts(results: dict[int, MatchResult]) -> None:
    wanted_by_zip: dict[Path, set[str]] = defaultdict(set)
    for result in results.values():
        if result.status != "matched" or not result.result_zip or not result.monitoring_location_identifier:
            continue
        for zip_path in split_paths(result.result_zip):
            wanted_by_zip[zip_path].add(result.monitoring_location_identifier)

    counts_by_zip_and_station: dict[tuple[Path, str], tuple[int, int]] = {}
    for zip_path, wanted_ids in sorted(wanted_by_zip.items()):
        result_counts: Counter[str] = Counter()
        activities_by_station: dict[str, set[str]] = defaultdict(set)
        for row in iter_zip_csv_rows(zip_path):
            station_id = (row.get("MonitoringLocationIdentifier") or "").strip()
            if station_id not in wanted_ids:
                continue
            result_counts[station_id] += 1
            activity_id = (row.get("ActivityIdentifier") or "").strip()
            if activity_id:
                activities_by_station[station_id].add(activity_id)
        for station_id in wanted_ids:
            counts_by_zip_and_station[(zip_path, station_id)] = (
                result_counts[station_id],
                len(activities_by_station.get(station_id, set())),
            )

    for result in results.values():
        if result.status != "matched":
            continue
        result_rows = 0
        activity_count = 0
        found_count = False
        for zip_path in split_paths(result.result_zip):
            key = (zip_path, result.monitoring_location_identifier)
            if key not in counts_by_zip_and_station:
                continue
            found_count = True
            zip_result_rows, zip_activity_count = counts_by_zip_and_station[key]
            result_rows += zip_result_rows
            activity_count += zip_activity_count
        if found_count:
            result.result_rows_at_station = str(result_rows)
            result.activity_count_at_station = str(activity_count)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Public data CSV with coordinates")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output CSV with appended WQP match columns")
    parser.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT_DIR, help="Directory containing WQP result zip files")
    parser.add_argument("--station-dir", type=Path, default=DEFAULT_STATION_DIR, help="Directory for WQP station metadata zip files")
    parser.add_argument("--lat-column", default="ACC_X", help="Latitude column in --input")
    parser.add_argument("--lon-column", default="ACC_Y", help="Longitude column in --input")
    parser.add_argument("--max-nearest-km", type=float, default=10.0, help="Maximum nearest-station distance")
    parser.add_argument("--sample-media", default=None, help="Semicolon-separated WQP sample media values")
    parser.add_argument("--characteristic-types", default=None, help="Semicolon-separated WQP characteristicType values")
    parser.add_argument(
        "--characteristic-names",
        default=None,
        help=(
            "Optional semicolon-separated WQP characteristicName values to apply to every characteristic group. "
            "Default: desalination-focused names chosen per group."
        ),
    )
    parser.add_argument("--providers", default=None, help="Semicolon-separated WQP providers")
    parser.add_argument(
        "--priority-characteristic-types",
        default=None,
        help=(
            "Semicolon-separated WQP characteristicType values whose stations are preferred when matching, "
            "so a point matches the nearest major-ion-chemistry station instead of a closer physical-only one. "
            'Default: "Inorganics, Major, Metals".'
        ),
    )
    parser.add_argument(
        "--no-analyte-priority",
        action="store_true",
        help="Disable analyte-prioritized matching and use the nearest station of any kind",
    )
    parser.add_argument(
        "--include-legacy-result-zips",
        action="store_true",
        help="Also use old broad WQP result zips that do not have a characteristic-group suffix",
    )
    parser.add_argument("--replace-stations", action="store_true", help="Replace station metadata zip files that already exist")
    parser.add_argument("--skip-station-download", action="store_true", help="Only use station metadata zip files already on disk")
    parser.add_argument("--skip-result-counts", action="store_true", help="Skip counting result/activity rows for matched stations")
    parser.add_argument("--timeout", type=int, default=180, help="Network timeout in seconds")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sample_media = parse_multi_value(args.sample_media, DEFAULT_SAMPLE_MEDIA)
    characteristic_types = parse_multi_value(args.characteristic_types, DEFAULT_CHARACTERISTIC_TYPES)
    characteristic_names = parse_optional_multi_value(args.characteristic_names)
    providers = parse_multi_value(args.providers, DEFAULT_PROVIDERS)
    priority_types: set[str] = (
        set()
        if args.no_analyte_priority
        else set(parse_multi_value(args.priority_characteristic_types, DEFAULT_PRIORITY_CHARACTERISTIC_TYPES))
    )

    sources = discover_sources(
        args.result_dir,
        args.station_dir,
        sample_media,
        characteristic_types,
        characteristic_names,
        providers,
        include_legacy_result_zips=args.include_legacy_result_zips,
    )
    print(f"Discovered {len(sources)} local WQP result zip sources", flush=True)
    ensure_station_zips(sources, replace=args.replace_stations, timeout=args.timeout, skip_download=args.skip_station_download)
    by_county, statewide = index_sources(sources)

    with args.input.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{args.input} has no header row")
        rows = list(reader)
        input_fields = reader.fieldnames

    results: dict[int, MatchResult] = {}
    groups: dict[tuple[Path, ...], list[PointRow]] = defaultdict(list)
    group_sources: dict[tuple[Path, ...], list[WqpSource]] = {}

    for index, row in enumerate(rows):
        lat = parse_float(row.get(args.lat_column, ""))
        lon = parse_float(row.get(args.lon_column, ""))
        if lat is None or lon is None:
            results[index] = MatchResult(
                status="skipped",
                method="missing_coordinates",
                note=f"missing {args.lat_column} or {args.lon_column}",
            )
            continue

        candidates: list[WqpSource] = []
        seen_paths: set[Path] = set()
        for key in candidate_search_keys(row):
            for source in by_county.get(key, []):
                if source.result_zip_path not in seen_paths:
                    seen_paths.add(source.result_zip_path)
                    candidates.append(source)

        # State-wide WQP zips contain all counties, so use them as fallback coverage.
        for source in statewide.get((row.get("STATE") or "").strip().upper(), []):
            if source.result_zip_path not in seen_paths:
                seen_paths.add(source.result_zip_path)
                candidates.append(source)

        if not candidates:
            results[index] = MatchResult(
                status="no_match",
                method="no_candidate_wqp_files",
                note="no downloaded WQP result zips found for this state/county search",
            )
            continue

        group_key = tuple(source.station_zip_path for source in candidates)
        group_sources[group_key] = candidates
        groups[group_key].append(PointRow(index=index, latitude=lat, longitude=lon, group_key=group_key))

    for group_index, (group_key, points) in enumerate(groups.items(), start=1):
        sources_for_group = group_sources[group_key]
        print(
            f"[{group_index}/{len(groups)}] Matching {len(points)} row(s) against {len(sources_for_group)} WQP source(s)",
            flush=True,
        )
        results.update(match_group(points, sources_for_group, args.max_nearest_km, priority_types))

    if not args.skip_result_counts:
        add_result_counts(results)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[*input_fields, *MATCH_COLUMNS])
        writer.writeheader()
        for index, row in enumerate(rows):
            writer.writerow({**row, **results[index].as_row()})

    counts: Counter[str] = Counter(f"{result.status}:{result.method}" for result in results.values())
    matched = sum(1 for result in results.values() if result.status == "matched")
    print(f"Wrote {len(rows)} rows to {args.output}", flush=True)
    print(f"Matched rows: {matched}", flush=True)
    for key in sorted(counts):
        print(f"{key}: {counts[key]}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

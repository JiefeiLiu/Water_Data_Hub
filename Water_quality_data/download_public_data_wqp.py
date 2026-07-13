#!/usr/bin/env python3
"""Download Water Quality Portal sample-result data for public-data counties."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import difflib
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
WATER_DATA_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = REPO_ROOT / "public_data" / "report207appendixA_all_tables.csv"
DEFAULT_DOWNLOAD_DIR = WATER_DATA_DIR / "wqp_result_zips"
DEFAULT_MANIFEST = WATER_DATA_DIR / "public_data_wqp_manifest.csv"
DEFAULT_UNMATCHED = WATER_DATA_DIR / "public_data_wqp_unmatched.csv"
DEFAULT_DOWNLOADED_SEARCHES = WATER_DATA_DIR / "public_data_wqp_downloaded_counties.json"
DEFAULT_OUTPUT_COUNTS = WATER_DATA_DIR / "outputs" / "public_data_wqp_count_summary.csv"

WQP_RESULT_SEARCH_URL = "https://www.waterqualitydata.us/data/Result/search"
WQP_CODES_URL = "https://www.waterqualitydata.us/Codes"
USER_AGENT = "Water-Hub-WQP-downloader/1.0"
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

STATE_ABBREVIATION_TO_FIPS = {
    "AL": "01",
    "AK": "02",
    "AZ": "04",
    "AR": "05",
    "CA": "06",
    "CO": "08",
    "CT": "09",
    "DE": "10",
    "DC": "11",
    "FL": "12",
    "GA": "13",
    "HI": "15",
    "ID": "16",
    "IL": "17",
    "IN": "18",
    "IA": "19",
    "KS": "20",
    "KY": "21",
    "LA": "22",
    "ME": "23",
    "MD": "24",
    "MA": "25",
    "MI": "26",
    "MN": "27",
    "MS": "28",
    "MO": "29",
    "MT": "30",
    "NE": "31",
    "NV": "32",
    "NH": "33",
    "NJ": "34",
    "NM": "35",
    "NY": "36",
    "NC": "37",
    "ND": "38",
    "OH": "39",
    "OK": "40",
    "OR": "41",
    "PA": "42",
    "RI": "44",
    "SC": "45",
    "SD": "46",
    "TN": "47",
    "TX": "48",
    "UT": "49",
    "VT": "50",
    "VA": "51",
    "WA": "53",
    "WV": "54",
    "WI": "55",
    "WY": "56",
}


@dataclass(frozen=True)
class SearchSpec:
    state: str
    county: str


@dataclass(frozen=True)
class CountyCode:
    value: str
    name: str
    providers: str


@dataclass
class DownloadRecord:
    source_state: str
    source_county: str
    search_county: str
    matched_county: str
    state_code: str
    county_code: str
    county_providers: str
    sample_media: str
    characteristic_types: str
    characteristic_names: str
    providers: str
    query_url: str
    filename: str
    local_path: str
    status: str
    total_site_count: str = ""
    nwis_site_count: str = ""
    storet_site_count: str = ""
    total_activity_count: str = ""
    nwis_activity_count: str = ""
    storet_activity_count: str = ""
    total_result_count: str = ""
    nwis_result_count: str = ""
    storet_result_count: str = ""
    warning: str = ""


def normalize_name(value: str) -> str:
    value = value.lower().replace("saint", "st")
    value = re.sub(r"\b(county|parish|borough|city and borough|municipality|census area)\b", "", value)
    return re.sub(r"[^a-z0-9]", "", value)


def county_tokens(raw_county: str) -> list[str]:
    county = (raw_county or "").strip()
    if not county or county.lower() == "none":
        return [""]
    return [part.strip() for part in re.split(r"\s*(?:&|/|;|\band\b)\s*", county, flags=re.IGNORECASE) if part.strip()]


def search_key(state: str, county: str) -> str:
    county_key = normalize_name(county) if county else "all_counties"
    return f"{state.upper()}|{county_key}"


def read_search_specs(input_csv: Path, skip_state_only: bool) -> list[SearchSpec]:
    specs: dict[tuple[str, str], SearchSpec] = {}
    with input_csv.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            state = (row.get("STATE") or "").strip().upper()
            if not state or state == "NONE":
                continue
            for county in county_tokens(row.get("COUNTY") or ""):
                if skip_state_only and not county:
                    continue
                specs.setdefault((state, normalize_name(county)), SearchSpec(state=state, county=county))
    return sorted(specs.values(), key=lambda spec: (spec.state, spec.county.upper()))


def parse_multi_value(value: str | None, default: list[str]) -> list[str]:
    if value is None:
        return default
    values = [item.strip() for item in value.split(";") if item.strip()]
    return values or default


def parse_optional_multi_value(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [item.strip() for item in value.split(";") if item.strip()]


def encode_semicolon_values(values: list[str]) -> str:
    return ";".join(values)


def open_json(url: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset))


def fetch_county_codes(state_code: str, timeout: int) -> list[CountyCode]:
    params = urllib.parse.urlencode({"statecode": state_code, "mimeType": "json"})
    payload = open_json(f"{WQP_CODES_URL}/countycode?{params}", timeout)
    counties: list[CountyCode] = []
    for item in payload.get("codes", []):
        desc = str(item.get("desc") or "")
        name = desc.rsplit(",", maxsplit=1)[-1].strip() if "," in desc else desc.strip()
        counties.append(
            CountyCode(
                value=str(item.get("value") or ""),
                name=name,
                providers=str(item.get("providers") or ""),
            )
        )
    return counties


def match_county(counties: list[CountyCode], county: str) -> CountyCode | None:
    normalized = normalize_name(county)
    by_name = {normalize_name(item.name): item for item in counties}
    if normalized in by_name:
        return by_name[normalized]

    matches = difflib.get_close_matches(normalized, list(by_name), n=1, cutoff=0.86)
    if matches:
        return by_name[matches[0]]
    return None


def make_query_url(
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
    return f"{WQP_RESULT_SEARCH_URL}?{urllib.parse.urlencode(params)}"


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "all"


def safe_filename(state: str, county: str, county_code: str, characteristic_type: str) -> str:
    county_slug = re.sub(r"[^A-Za-z0-9]+", "_", county.strip()).strip("_").lower() or "all_counties"
    code_slug = county_code.replace(":", "_")
    characteristic_slug = slugify(characteristic_type)
    return f"{state.upper()}_{county_slug}_{code_slug}_{characteristic_slug}_wqp_results.zip"


def collect_records(
    specs: list[SearchSpec],
    sample_media: list[str],
    characteristic_types: list[str],
    characteristic_names_override: list[str] | None,
    providers: list[str],
    timeout: int,
    delay: float,
) -> tuple[list[DownloadRecord], list[dict[str, str]]]:
    records: list[DownloadRecord] = []
    unmatched: list[dict[str, str]] = []
    county_code_cache: dict[str, list[CountyCode]] = {}

    for index, spec in enumerate(specs, start=1):
        print(f"[{index}/{len(specs)}] Matching {spec.state} {spec.county or '(all counties)'}", flush=True)
        state_fips = STATE_ABBREVIATION_TO_FIPS.get(spec.state)
        if not state_fips:
            unmatched.append({"state": spec.state, "county": spec.county, "reason": "state abbreviation not recognized"})
            continue

        state_code = f"US:{state_fips}"
        if not spec.county:
            county_code = state_code
            matched_county = ""
            county_providers = ""
        else:
            if state_code not in county_code_cache:
                try:
                    county_code_cache[state_code] = fetch_county_codes(state_code, timeout)
                except Exception as exc:
                    unmatched.append({"state": spec.state, "county": spec.county, "reason": f"failed to fetch WQP county codes: {exc}"})
                    continue
                time.sleep(delay)
            match = match_county(county_code_cache[state_code], spec.county)
            if not match:
                unmatched.append({"state": spec.state, "county": spec.county, "reason": "county not found in WQP county codes"})
                continue
            county_code = match.value
            matched_county = match.name
            county_providers = match.providers

        for characteristic_type in characteristic_types:
            characteristic_names = (
                characteristic_names_override
                if characteristic_names_override is not None
                else DEFAULT_CHARACTERISTIC_NAMES_BY_TYPE.get(characteristic_type, [])
            )
            query_url = make_query_url(county_code, sample_media, [characteristic_type], characteristic_names, providers)
            filename = safe_filename(spec.state, matched_county or spec.county, county_code, characteristic_type)
            records.append(
                DownloadRecord(
                    source_state=spec.state,
                    source_county=spec.county or "none",
                    search_county=spec.county,
                    matched_county=matched_county,
                    state_code=state_code,
                    county_code=county_code,
                    county_providers=county_providers,
                    sample_media=encode_semicolon_values(sample_media),
                    characteristic_types=characteristic_type,
                    characteristic_names=encode_semicolon_values(characteristic_names),
                    providers=encode_semicolon_values(providers),
                    query_url=query_url,
                    filename=filename,
                    local_path="",
                    status="pending",
                )
            )

    return records, unmatched


COUNT_HEADERS = [
    "total_site_count",
    "nwis_site_count",
    "storet_site_count",
    "total_activity_count",
    "nwis_activity_count",
    "storet_activity_count",
    "total_result_count",
    "nwis_result_count",
    "storet_result_count",
]


def populate_count_headers(record: DownloadRecord, timeout: int) -> None:
    request = urllib.request.Request(record.query_url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for header in COUNT_HEADERS:
                setattr(record, header, response.headers.get(header.replace("_", "-"), ""))
            warnings = response.headers.get_all("Warning") or []
            record.warning = " | ".join(warnings)
    except Exception as exc:
        record.warning = f"failed to fetch count headers: {exc}"


def populate_all_count_headers(records: list[DownloadRecord], timeout: int, delay: float) -> None:
    by_url: dict[str, DownloadRecord] = {}
    for record in records:
        by_url.setdefault(record.query_url, record)

    for index, representative in enumerate(by_url.values(), start=1):
        print(f"[{index}/{len(by_url)}] Checking counts for {representative.county_code}", flush=True)
        populate_count_headers(representative, timeout)
        for record in records:
            if record.query_url == representative.query_url and record is not representative:
                for header in COUNT_HEADERS:
                    setattr(record, header, getattr(representative, header))
                record.warning = representative.warning
        time.sleep(delay)


def download_url(url: str, destination: Path, timeout: int, replace: bool) -> str:
    if destination.exists() and not replace:
        return "skipped_existing"

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response, temp_path.open("wb") as handle:
        while True:
            chunk = response.read(CHUNK_SIZE)
            if not chunk:
                break
            handle.write(chunk)
    temp_path.replace(destination)
    return "downloaded"


def download_records(records: list[DownloadRecord], download_dir: Path, timeout: int, replace: bool) -> None:
    by_url: dict[str, DownloadRecord] = {}
    for record in records:
        by_url.setdefault(record.query_url, record)

    for index, record in enumerate(by_url.values(), start=1):
        destination = download_dir / record.state_code.replace(":", "_") / record.filename
        print(f"[{index}/{len(by_url)}] Downloading {record.county_code}: {record.filename}", flush=True)
        try:
            status = download_url(record.query_url, destination, timeout, replace)
        except Exception as exc:
            status = f"failed: {exc}"
        for item in records:
            if item.query_url == record.query_url:
                item.local_path = str(destination)
                item.status = status


def write_manifest(records: list[DownloadRecord], manifest_path: Path) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "source_state",
        "source_county",
        "search_county",
        "matched_county",
        "state_code",
        "county_code",
        "county_providers",
        "sample_media",
        "characteristic_types",
        "characteristic_names",
        "providers",
        "filename",
        "local_path",
        "status",
        *COUNT_HEADERS,
        "warning",
        "query_url",
    ]
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow({field: getattr(record, field) for field in fieldnames})


def write_unmatched(unmatched: list[dict[str, str]], unmatched_path: Path) -> None:
    unmatched_path.parent.mkdir(parents=True, exist_ok=True)
    with unmatched_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["state", "county", "reason"])
        writer.writeheader()
        writer.writerows(unmatched)


def read_manifest_records(manifest_path: Path) -> list[DownloadRecord]:
    records: list[DownloadRecord] = []
    with manifest_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            records.append(
                DownloadRecord(
                    source_state=row.get("source_state", ""),
                    source_county=row.get("source_county", ""),
                    search_county=row.get("search_county", ""),
                    matched_county=row.get("matched_county", ""),
                    state_code=row.get("state_code", ""),
                    county_code=row.get("county_code", ""),
                    county_providers=row.get("county_providers", ""),
                    sample_media=row.get("sample_media", ""),
                    characteristic_types=row.get("characteristic_types", ""),
                    characteristic_names=row.get("characteristic_names", ""),
                    providers=row.get("providers", ""),
                    query_url=row.get("query_url", ""),
                    filename=row.get("filename", ""),
                    local_path=row.get("local_path", ""),
                    status=row.get("status", ""),
                    total_site_count=row.get("total_site_count", ""),
                    nwis_site_count=row.get("nwis_site_count", ""),
                    storet_site_count=row.get("storet_site_count", ""),
                    total_activity_count=row.get("total_activity_count", ""),
                    nwis_activity_count=row.get("nwis_activity_count", ""),
                    storet_activity_count=row.get("storet_activity_count", ""),
                    total_result_count=row.get("total_result_count", ""),
                    nwis_result_count=row.get("nwis_result_count", ""),
                    storet_result_count=row.get("storet_result_count", ""),
                    warning=row.get("warning", ""),
                )
            )
    return records


def read_unmatched(unmatched_path: Path) -> list[dict[str, str]]:
    if not unmatched_path.exists():
        return []
    with unmatched_path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_downloaded_searches(
    records: list[DownloadRecord],
    unmatched: list[dict[str, str]],
    downloaded_searches_path: Path,
    manifest_path: Path,
    download_dir: Path,
) -> None:
    groups: dict[str, dict[str, Any]] = {}
    for record in records:
        key = search_key(record.source_state, record.source_county)
        group = groups.setdefault(
            key,
            {
                "state": record.source_state,
                "source_county": record.source_county,
                "search_county": record.search_county,
                "matched_county": record.matched_county,
                "state_code": record.state_code,
                "county_code": record.county_code,
                "source_search_key": key,
                "matched_search_key": search_key(record.source_state, record.matched_county or record.source_county),
                "manifest_rows": 0,
                "filenames": set(),
                "query_urls": set(),
                "statuses": set(),
            },
        )
        group["manifest_rows"] += 1
        group["filenames"].add(record.filename)
        group["query_urls"].add(record.query_url)
        group["statuses"].add(record.status)

    downloaded_searches = []
    for group in groups.values():
        statuses = sorted(group.pop("statuses"))
        failed = any(status.startswith("failed") for status in statuses)
        manifest_only = any(status == "manifest_only" for status in statuses)
        if failed:
            download_status = "failed_or_partial"
        elif manifest_only:
            download_status = "manifest_only"
        else:
            download_status = "complete"
        group.update(
            {
                "download_status": download_status,
                "statuses": statuses,
                "filenames": sorted(group.pop("filenames")),
                "query_urls": sorted(group.pop("query_urls")),
            }
        )
        downloaded_searches.append(group)

    payload = {
        "description": (
            "Completed Water Quality Portal state/county result searches. Future runs can use "
            "source_search_key or matched_search_key to skip counties already downloaded."
        ),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_manifest": str(manifest_path),
        "download_dir": str(download_dir),
        "downloaded_searches": sorted(
            downloaded_searches,
            key=lambda item: (str(item["state"]), str(item["source_county"]).upper()),
        ),
        "unmatched_searches": unmatched,
    }

    downloaded_searches_path.parent.mkdir(parents=True, exist_ok=True)
    with downloaded_searches_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def read_downloaded_search_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    keys = set()
    for search in data.get("downloaded_searches", []):
        if search.get("download_status") != "complete":
            continue
        query_urls = [str(url) for url in search.get("query_urls", [])]
        if query_urls and not all("characteristicName=" in url for url in query_urls):
            continue
        keys.add(str(search.get("source_search_key") or ""))
        keys.add(str(search.get("matched_search_key") or ""))
    return {key for key in keys if key}


def filter_recorded_searches(specs: list[SearchSpec], downloaded_searches_path: Path) -> tuple[list[SearchSpec], int]:
    downloaded_keys = read_downloaded_search_keys(downloaded_searches_path)
    if not downloaded_keys:
        return specs, 0
    filtered = [spec for spec in specs if search_key(spec.state, spec.county) not in downloaded_keys]
    return filtered, len(specs) - len(filtered)


def write_count_summary(records: list[DownloadRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    unique: dict[str, DownloadRecord] = {}
    for record in records:
        unique.setdefault(record.query_url, record)

    fieldnames = [
        "state_code",
        "county_code",
        "matched_county",
        "total_site_count",
        "total_activity_count",
        "total_result_count",
        "nwis_result_count",
        "storet_result_count",
        "query_url",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in sorted(unique.values(), key=lambda item: (item.state_code, item.county_code)):
            writer.writerow({field: getattr(record, field) for field in fieldnames})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="CSV with STATE and COUNTY columns")
    parser.add_argument("--download-dir", type=Path, default=DEFAULT_DOWNLOAD_DIR, help="Directory for downloaded WQP zip files")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="Output manifest CSV")
    parser.add_argument("--unmatched", type=Path, default=DEFAULT_UNMATCHED, help="Output CSV for unmatched searches")
    parser.add_argument("--count-summary", type=Path, default=DEFAULT_OUTPUT_COUNTS, help="Output CSV of unique county count headers")
    parser.add_argument(
        "--downloaded-searches",
        type=Path,
        default=DEFAULT_DOWNLOADED_SEARCHES,
        help="JSON registry of completed state/county searches",
    )
    parser.add_argument(
        "--sample-media",
        default=None,
        help="Semicolon-separated WQP sample media values. Default: water;Water",
    )
    parser.add_argument(
        "--characteristic-types",
        default=None,
        help=(
            "Semicolon-separated WQP characteristicType values. Each value is queried separately. "
            "Default: Inorganics, Major, Metals;Physical"
        ),
    )
    parser.add_argument(
        "--characteristic-names",
        default=None,
        help=(
            "Optional semicolon-separated WQP characteristicName values to apply to every characteristic group. "
            "Default: desalination-focused names chosen per group."
        ),
    )
    parser.add_argument(
        "--providers",
        default=None,
        help="Semicolon-separated WQP providers. Default: NWIS;STEWARDS;STORET",
    )
    parser.add_argument("--manifest-only", action="store_true", help="Write manifests without downloading result zip files")
    parser.add_argument("--skip-counts", action="store_true", help="Do not call WQP HEAD requests for result-count headers")
    parser.add_argument("--replace", action="store_true", help="Replace zip files that already exist")
    parser.add_argument("--skip-state-only", action="store_true", help="Skip rows where COUNTY is blank or none")
    parser.add_argument(
        "--skip-recorded-searches",
        action="store_true",
        help="Skip state/county searches already marked complete in --downloaded-searches",
    )
    parser.add_argument(
        "--registry-from-manifest",
        action="store_true",
        help="Write --downloaded-searches from existing --manifest/--unmatched and exit without network access",
    )
    parser.add_argument("--timeout", type=int, default=180, help="Network timeout in seconds")
    parser.add_argument("--delay", type=float, default=0.2, help="Delay between WQP requests")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.registry_from_manifest:
        records = read_manifest_records(args.manifest)
        unmatched = read_unmatched(args.unmatched)
        write_downloaded_searches(records, unmatched, args.downloaded_searches, args.manifest, args.download_dir)
        print(f"Wrote {args.downloaded_searches} from {args.manifest}", flush=True)
        return 0

    sample_media = parse_multi_value(args.sample_media, DEFAULT_SAMPLE_MEDIA)
    characteristic_types = parse_multi_value(args.characteristic_types, DEFAULT_CHARACTERISTIC_TYPES)
    characteristic_names = parse_optional_multi_value(args.characteristic_names)
    providers = parse_multi_value(args.providers, DEFAULT_PROVIDERS)

    specs = read_search_specs(args.input, args.skip_state_only)
    print(f"Loaded {len(specs)} unique state/county searches from {args.input}", flush=True)
    if args.skip_recorded_searches:
        specs, skipped = filter_recorded_searches(specs, args.downloaded_searches)
        print(f"Skipped {skipped} searches already recorded in {args.downloaded_searches}", flush=True)
        print(f"Remaining searches: {len(specs)}", flush=True)
    if not specs:
        print("No new state/county searches to run.", flush=True)
        return 0

    records, unmatched = collect_records(
        specs,
        sample_media,
        characteristic_types,
        characteristic_names,
        providers,
        args.timeout,
        args.delay,
    )
    if not args.skip_counts:
        populate_all_count_headers(records, args.timeout, args.delay)

    if args.manifest_only:
        for record in records:
            destination = args.download_dir / record.state_code.replace(":", "_") / record.filename
            record.local_path = str(destination)
            record.status = "manifest_only"
    else:
        download_records(records, args.download_dir, args.timeout, args.replace)

    write_manifest(records, args.manifest)
    write_unmatched(unmatched, args.unmatched)
    write_downloaded_searches(records, unmatched, args.downloaded_searches, args.manifest, args.download_dir)
    write_count_summary(records, args.count_summary)

    unique_queries = len({record.query_url for record in records})
    failed = sum(1 for record in records if record.status.startswith("failed"))
    print(f"Matched {len(records)} manifest rows across {unique_queries} unique WQP county queries", flush=True)
    print(f"Unmatched searches: {len(unmatched)}", flush=True)
    print(f"Failed downloads: {failed}", flush=True)
    print(f"Manifest: {args.manifest}", flush=True)
    print(f"Unmatched: {args.unmatched}", flush=True)
    print(f"Count summary: {args.count_summary}", flush=True)
    print(f"Downloaded searches: {args.downloaded_searches}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

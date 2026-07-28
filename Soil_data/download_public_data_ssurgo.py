#!/usr/bin/env python3
"""Download SSURGO zip packages for state/county pairs in the public data CSV."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import difflib
import html
import http.cookiejar
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from download_ssurgo import CHUNK_SIZE, quote_url_path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "public_data" / "metadata" / "report207appendixA_all_tables.csv"
DEFAULT_DOWNLOAD_DIR = Path(__file__).resolve().parent / "public_data_ssurgo_zips"
DEFAULT_MANIFEST = Path(__file__).resolve().parent / "metadata" / "public_data_ssurgo_manifest.csv"
DEFAULT_UNMATCHED = Path(__file__).resolve().parent / "metadata" / "public_data_ssurgo_unmatched.csv"
DEFAULT_DOWNLOADED_SEARCHES = Path(__file__).resolve().parent / "metadata" / "public_data_ssurgo_downloaded_counties.json"
WSS_BASE = "https://websoilsurvey.sc.egov.usda.gov/App"
ZIP_RE = re.compile(r"https://websoilsurvey\.sc\.egov\.usda\.gov/DSD/Download/Cache/SSA/[^\"<>\\]+?\.zip")
AREA_SYMBOL_RE = re.compile(r"wss_SSA_([A-Z0-9]+)_")
OPTION_RE = re.compile(r'<option value="([^"]+)">\s*(.*?)\s*</option>', re.DOTALL)


@dataclass(frozen=True)
class SearchSpec:
    state: str
    county: str


@dataclass
class DownloadRecord:
    source_state: str
    source_county: str
    search_county: str
    matched_county: str
    county_code: str
    area_symbol: str
    url: str
    filename: str
    local_path: str
    status: str


def clean_js_html_text(value: str) -> str:
    return html.unescape(value.replace("\\r", "").replace("\\n", "").replace("\\'", "'")).strip()


def normalize_name(value: str) -> str:
    value = value.lower().replace("saint", "st")
    return re.sub(r"[^a-z0-9]", "", value)


def search_key(state: str, county: str) -> str:
    county_key = normalize_name(county) if county and county.lower() != "none" else "all_counties"
    return f"{state.upper()}|{county_key}"


def county_tokens(raw_county: str) -> list[str]:
    county = (raw_county or "").strip()
    if not county or county.lower() == "none":
        return [""]
    return [part.strip() for part in re.split(r"\s*(?:&|/|;|\band\b)\s*", county, flags=re.IGNORECASE) if part.strip()]


def read_search_specs(input_csv: Path, skip_state_only: bool) -> list[SearchSpec]:
    specs: set[SearchSpec] = set()
    with input_csv.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            state = (row.get("STATE") or "").strip().upper()
            if not state or state == "NONE":
                continue
            for county in county_tokens(row.get("COUNTY") or ""):
                if skip_state_only and not county:
                    continue
                specs.add(SearchSpec(state=state, county=county))
    return sorted(specs, key=lambda spec: (spec.state, spec.county.upper()))


def read_downloaded_search_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    searches = data.get("downloaded_searches", [])
    keys = {
        search.get("source_search_key", "")
        for search in searches
        if search.get("download_status") == "complete"
    }
    keys.update(
        search.get("matched_search_key", "")
        for search in searches
        if search.get("download_status") == "complete"
    )
    return {key for key in keys if key}


def filter_recorded_searches(specs: list[SearchSpec], downloaded_searches_path: Path) -> tuple[list[SearchSpec], int]:
    downloaded_keys = read_downloaded_search_keys(downloaded_searches_path)
    if not downloaded_keys:
        return specs, 0
    filtered = [spec for spec in specs if search_key(spec.state, spec.county) not in downloaded_keys]
    return filtered, len(specs) - len(filtered)


class WebSoilSurveyClient:
    def __init__(self, timeout: int) -> None:
        self.timeout = timeout
        self.cookiejar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookiejar))

    def open(self, url: str, data: dict[str, str] | None = None) -> str:
        encoded_data = None if data is None else urllib.parse.urlencode(data).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=encoded_data,
            headers={"User-Agent": "Water-Hub-SSURGO-downloader/1.0"},
        )
        with self.opener.open(request, timeout=self.timeout) as response:
            return response.read().decode(response.headers.get_content_charset() or "iso-8859-1", errors="replace")

    def get_script(self, params: dict[str, str]) -> str:
        url = f"{WSS_BASE}/GetScript.dynamic?{urllib.parse.urlencode(params)}"
        return self.open(url)

    def start_session(self) -> None:
        self.open(f"{WSS_BASE}/WebSoilSurvey.aspx")
        self.get_script({"command": "changeoutertab", "newtab": "Download Soils Data"})
        self.open(f"{WSS_BASE}/WebSoilSurvey.aspx")

    def fetch_state_form(self, state: str) -> str:
        return self.get_script(
            {
                "command": "updatedownloadsoilsdataform",
                "update": "updatestate",
                "area": "areaSSA",
                "state": state,
                "ssadate": "",
                "soilsurveyareasortby": "soilsurveyareasortbyareasymbol",
                "soilsurveyareaincludetemplatedb": "true",
            }
        )

    def fetch_county_form(self, state: str, county_code: str) -> str:
        return self.get_script(
            {
                "command": "updatedownloadsoilsdataform",
                "update": "updatessasortby",
                "area": "areaSSA",
                "state": state,
                "county": county_code,
                "ssadate": "",
                "soilsurveyareasortby": "soilsurveyareasortbyareasymbol",
                "soilsurveyareaincludetemplatedb": "true",
            }
        )


def parse_zip_urls(form_text: str) -> list[str]:
    return sorted(set(ZIP_RE.findall(form_text)))


def parse_area_symbol(url: str) -> str:
    match = AREA_SYMBOL_RE.search(Path(urllib.parse.urlsplit(url).path).name)
    if not match:
        return ""
    return match.group(1)


def parse_county_options(form_text: str, state: str) -> dict[str, tuple[str, str]]:
    options: dict[str, tuple[str, str]] = {}
    for value, label in OPTION_RE.findall(form_text):
        label = clean_js_html_text(label)
        if value.startswith(state) and len(value) == 5 and label:
            options[normalize_name(label)] = (value, label)
    return options


def match_county(options: dict[str, tuple[str, str]], county: str) -> tuple[str, str] | None:
    normalized = normalize_name(county)
    if normalized in options:
        return options[normalized]

    keys = list(options)
    matches = difflib.get_close_matches(normalized, keys, n=1, cutoff=0.84)
    if matches:
        return options[matches[0]]
    return None


def collect_records(client: WebSoilSurveyClient, specs: list[SearchSpec], delay: float) -> tuple[list[DownloadRecord], list[dict[str, str]]]:
    records: list[DownloadRecord] = []
    unmatched: list[dict[str, str]] = []
    state_forms: dict[str, str] = {}

    for index, spec in enumerate(specs, start=1):
        print(f"[{index}/{len(specs)}] Searching {spec.state} {spec.county or '(all counties)'}", flush=True)
        if spec.state not in state_forms:
            state_forms[spec.state] = client.fetch_state_form(spec.state)
            time.sleep(delay)

        form_text = state_forms[spec.state]
        matched_county = ""
        county_code = ""
        if spec.county:
            options = parse_county_options(form_text, spec.state)
            match = match_county(options, spec.county)
            if not match:
                unmatched.append({"state": spec.state, "county": spec.county, "reason": "county not found in Web Soil Survey"})
                continue
            county_code, matched_county = match
            form_text = client.fetch_county_form(spec.state, county_code)
            time.sleep(delay)

        urls = parse_zip_urls(form_text)
        if not urls:
            unmatched.append({"state": spec.state, "county": spec.county, "reason": "no SSURGO download links returned"})
            continue

        for url in urls:
            filename = Path(urllib.parse.urlsplit(url).path).name
            area_symbol = parse_area_symbol(url)
            records.append(
                DownloadRecord(
                    source_state=spec.state,
                    source_county=spec.county or "none",
                    search_county=spec.county,
                    matched_county=matched_county,
                    county_code=county_code,
                    area_symbol=area_symbol,
                    url=url,
                    filename=filename,
                    local_path="",
                    status="pending",
                )
            )

    return records, unmatched


def download_zip(url: str, destination: Path, timeout: int, replace: bool) -> str:
    if destination.exists() and not replace:
        return "skipped_existing"

    request = urllib.request.Request(
        quote_url_path(url),
        headers={"User-Agent": "Water-Hub-SSURGO-downloader/1.0"},
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(destination.suffix + ".part")
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
        by_url.setdefault(record.url, record)

    for index, record in enumerate(by_url.values(), start=1):
        area_dir = download_dir / (record.area_symbol or "unknown")
        destination = area_dir / record.filename
        print(f"[{index}/{len(by_url)}] Downloading {record.area_symbol}: {record.filename}", flush=True)
        try:
            status = download_zip(record.url, destination, timeout, replace)
        except Exception as exc:
            status = f"failed: {exc}"
        for item in records:
            if item.url == record.url:
                item.local_path = str(destination)
                item.status = status


def write_manifest(records: list[DownloadRecord], manifest_path: Path) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "source_state",
        "source_county",
        "search_county",
        "matched_county",
        "county_code",
        "area_symbol",
        "filename",
        "local_path",
        "status",
        "url",
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
                    county_code=row.get("county_code", ""),
                    area_symbol=row.get("area_symbol", ""),
                    url=row.get("url", ""),
                    filename=row.get("filename", ""),
                    local_path=row.get("local_path", ""),
                    status=row.get("status", ""),
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
    groups: dict[str, dict[str, object]] = {}
    for record in records:
        key = search_key(record.source_state, record.source_county)
        group = groups.setdefault(
            key,
            {
                "state": record.source_state,
                "source_county": record.source_county,
                "search_county": record.search_county,
                "matched_county": record.matched_county,
                "county_code": record.county_code,
                "source_search_key": key,
                "matched_search_key": search_key(record.source_state, record.matched_county or record.source_county),
                "manifest_rows": 0,
                "area_symbols": set(),
                "filenames": set(),
                "urls": set(),
                "statuses": set(),
            },
        )
        group["manifest_rows"] = int(group["manifest_rows"]) + 1
        group["area_symbols"].add(record.area_symbol)
        group["filenames"].add(record.filename)
        group["urls"].add(record.url)
        group["statuses"].add(record.status)

    downloaded_searches = []
    for group in groups.values():
        statuses = sorted(group.pop("statuses"))
        area_symbols = sorted(symbol for symbol in group.pop("area_symbols") if symbol)
        filenames = sorted(filename for filename in group.pop("filenames") if filename)
        urls = sorted(url for url in group.pop("urls") if url)
        failed = any(status.startswith("failed") for status in statuses)
        group.update(
            {
                "download_status": "failed_or_partial" if failed else "complete",
                "statuses": statuses,
                "unique_zip_count": len(urls),
                "area_symbols": area_symbols,
                "filenames": filenames,
                "urls": urls,
            }
        )
        downloaded_searches.append(group)

    payload = {
        "description": (
            "Completed SSURGO state/county searches. Future public-data downloads can use "
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="CSV with STATE and COUNTY columns")
    parser.add_argument("--download-dir", type=Path, default=DEFAULT_DOWNLOAD_DIR, help="Directory for downloaded zip files")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="Output manifest CSV")
    parser.add_argument("--unmatched", type=Path, default=DEFAULT_UNMATCHED, help="Output CSV for unmatched searches")
    parser.add_argument(
        "--downloaded-searches",
        type=Path,
        default=DEFAULT_DOWNLOADED_SEARCHES,
        help="JSON registry of completed state/county searches",
    )
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
    parser.add_argument("--manifest-only", action="store_true", help="Search and write manifests without downloading zip files")
    parser.add_argument("--replace", action="store_true", help="Replace zip files that already exist")
    parser.add_argument("--skip-state-only", action="store_true", help="Skip rows where COUNTY is blank or none")
    parser.add_argument("--timeout", type=int, default=180, help="Network timeout in seconds")
    parser.add_argument("--delay", type=float, default=0.2, help="Delay between Web Soil Survey requests")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.registry_from_manifest:
        records = read_manifest_records(args.manifest)
        unmatched = read_unmatched(args.unmatched)
        write_downloaded_searches(records, unmatched, args.downloaded_searches, args.manifest, args.download_dir)
        print(f"Wrote {args.downloaded_searches} from {args.manifest}", flush=True)
        return 0

    specs = read_search_specs(args.input, args.skip_state_only)
    print(f"Loaded {len(specs)} unique state/county searches from {args.input}", flush=True)
    if args.skip_recorded_searches:
        specs, skipped = filter_recorded_searches(specs, args.downloaded_searches)
        print(f"Skipped {skipped} searches already recorded in {args.downloaded_searches}", flush=True)
        print(f"Remaining searches: {len(specs)}", flush=True)
    if not specs:
        print("No new state/county searches to run.", flush=True)
        return 0

    client = WebSoilSurveyClient(timeout=args.timeout)
    client.start_session()
    records, unmatched = collect_records(client, specs, args.delay)

    if not args.manifest_only:
        download_records(records, args.download_dir, args.timeout, args.replace)
    else:
        for record in records:
            area_dir = args.download_dir / (record.area_symbol or "unknown")
            record.local_path = str(area_dir / record.filename)
            record.status = "manifest_only"

    write_manifest(records, args.manifest)
    write_unmatched(unmatched, args.unmatched)
    write_downloaded_searches(records, unmatched, args.downloaded_searches, args.manifest, args.download_dir)

    unique_downloads = len({record.url for record in records})
    failed = sum(1 for record in records if record.status.startswith("failed"))
    print(f"Matched {len(records)} rows across {unique_downloads} unique SSURGO zip packages", flush=True)
    print(f"Unmatched searches: {len(unmatched)}", flush=True)
    print(f"Failed downloads: {failed}", flush=True)
    print(f"Manifest: {args.manifest}", flush=True)
    print(f"Unmatched: {args.unmatched}", flush=True)
    print(f"Downloaded searches: {args.downloaded_searches}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

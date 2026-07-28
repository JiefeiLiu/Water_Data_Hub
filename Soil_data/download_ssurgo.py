#!/usr/bin/env python3
"""Download and unpack a SSURGO soil survey export.

The Web Soil Survey download UI generates zip files for survey areas such as
FL071. This script handles the repeatable part of the workflow once you have a
download URL: stream the zip, unpack it safely, and check that the expected
SSURGO folders are present.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


DEFAULT_AREA_SYMBOL = "FL071"
DEFAULT_OUTPUT_ROOT = Path(__file__).parent
CHUNK_SIZE = 1024 * 1024


def quote_url_path(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(parts.path, safe="/")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def normalize_area_symbol(area_symbol: str) -> str:
    cleaned = area_symbol.strip().upper()
    if not cleaned:
        raise ValueError("area symbol cannot be empty")
    if not cleaned.isalnum():
        raise ValueError(f"area symbol must be letters/numbers only: {area_symbol!r}")
    return cleaned


def default_candidate_urls(area_symbol: str) -> list[str]:
    """Return common Web Soil Survey cache URL patterns for a survey area.

    WSS cache file names can vary by export path and date. These candidates are
    useful when the standard cache file exists; otherwise pass --url with the
    exact link copied from Web Soil Survey's Download Soils Data tab.
    """

    lower = area_symbol.lower()
    return [
        f"https://websoilsurvey.sc.egov.usda.gov/DSD/Download/Cache/SSA/soil_{lower}.zip",
        f"https://websoilsurvey.sc.egov.usda.gov/DSD/Download/Cache/SSA/soil_{area_symbol}.zip",
        f"https://websoilsurvey.sc.egov.usda.gov/DSD/Download/Cache/SSA/wss_SSA_{area_symbol}.zip",
    ]


def download_file(url: str, destination: Path, timeout: int) -> None:
    request = urllib.request.Request(
        quote_url_path(url),
        headers={"User-Agent": "Water-Hub-SSURGO-downloader/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "")
        if "text/html" in content_type.lower() or "xml" in content_type.lower():
            preview = response.read(500).decode("utf-8", errors="replace")
            raise ValueError(f"download URL returned {content_type}, not a zip file: {preview[:200]}")

        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as handle:
            while True:
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                handle.write(chunk)


def assert_safe_zip_member(member_name: str) -> None:
    member_path = Path(member_name)
    if member_path.is_absolute() or ".." in member_path.parts:
        raise ValueError(f"unsafe path in zip file: {member_name}")


def unpack_zip(zip_path: Path, destination: Path, replace: bool) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        bad_file = archive.testzip()
        if bad_file is not None:
            raise ValueError(f"zip integrity check failed at {bad_file}")

        for member in archive.namelist():
            assert_safe_zip_member(member)

        if destination.exists():
            if not replace:
                raise FileExistsError(f"{destination} already exists; use --replace to overwrite it")
            shutil.rmtree(destination)
        destination.mkdir(parents=True)
        archive.extractall(destination)


def find_ssurgo_root(destination: Path, area_symbol: str) -> Path:
    candidates = [destination, destination / f"soil_{area_symbol.lower()}", destination / area_symbol]
    candidates.extend(path for path in destination.iterdir() if path.is_dir())
    candidates.extend(path.parent for path in destination.rglob("spatial") if path.is_dir())
    for candidate in candidates:
        if (candidate / "spatial").is_dir() and (candidate / "tabular").is_dir():
            return candidate
    raise FileNotFoundError(f"could not find SSURGO spatial/ and tabular/ folders under {destination}")


def download_ssurgo(area_symbol: str, output_root: Path, urls: list[str], replace: bool, timeout: int) -> Path:
    target_dir = output_root / area_symbol
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix=f"ssurgo_{area_symbol.lower()}_") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        zip_path = temp_dir / f"soil_{area_symbol.lower()}.zip"
        for url in urls:
            try:
                print(f"Trying {url}")
                download_file(url, zip_path, timeout)
                extract_dir = temp_dir / "extract"
                if extract_dir.exists():
                    shutil.rmtree(extract_dir)
                unpack_zip(zip_path, extract_dir, replace=True)
                ssurgo_root = find_ssurgo_root(extract_dir, area_symbol)
                if target_dir.exists():
                    if not replace:
                        raise FileExistsError(f"{target_dir} already exists; use --replace to overwrite it")
                    shutil.rmtree(target_dir)
                output_root.mkdir(parents=True, exist_ok=True)
                shutil.move(str(ssurgo_root), target_dir)
                return target_dir
            except (OSError, urllib.error.URLError, ValueError, zipfile.BadZipFile) as exc:
                errors.append(f"{url}: {exc}")

    message = "\n".join(errors)
    raise RuntimeError(f"all download attempts failed for {area_symbol}:\n{message}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("area_symbol", nargs="?", default=DEFAULT_AREA_SYMBOL, help="SSURGO survey area symbol")
    parser.add_argument(
        "--url",
        action="append",
        dest="urls",
        help="Exact SSURGO zip URL. Can be provided more than once; tried in order.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Directory where the survey folder should be written",
    )
    parser.add_argument("--replace", action="store_true", help="Overwrite an existing survey folder")
    parser.add_argument("--timeout", type=int, default=120, help="Network timeout in seconds")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        area_symbol = normalize_area_symbol(args.area_symbol)
        urls = args.urls or default_candidate_urls(area_symbol)
        output_path = download_ssurgo(area_symbol, args.output_root, urls, args.replace, args.timeout)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Downloaded and unpacked {area_symbol} to {output_path}")
    print("Next: run python Soil_data/extract_fl071_soil_values.py to regenerate the processed CSV.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

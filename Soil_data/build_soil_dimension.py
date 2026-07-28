#!/usr/bin/env python3
"""Build a combined per-mukey soil-feature dimension table, keyed by mukey.

This is the soil "library" side of the ID-linked design: one row per
(mukey x component x horizon) with the expert-selected features, deduplicated
across polygons and combined across survey areas. Plants link to it by the
`mukey` their coordinate matched (see match_public_data_soil_locations.py,
column `soil_match_mukey`), so no soil detail is flattened away.

By default it reads the survey zips referenced by the plant soil-match file, so
the dimension covers exactly the map units the plants need. `mukey` is
nationally unique in SSURGO, so rows from different surveys never collide.
"""

from __future__ import annotations

import argparse
import csv
import zipfile
from pathlib import Path

from soil_feature_builder import REQUIRED_STEMS, SoilFeatureBuilder, read_selected_columns
from ssurgo_full_database import inventory_from_rows, metadata_columns_from_rows, survey_root, zip_rows


REPO_ROOT = Path(__file__).resolve().parents[1]
SOIL_DATA_DIR = Path(__file__).resolve().parent
DEFAULT_DICTIONARY = SOIL_DATA_DIR / "metadata" / "Selected_columns_dictionary.csv"
DEFAULT_MATCH_FILE = REPO_ROOT / "public_data" / "processed_data" / "report207appendixA_all_tables_labeled_acc_soil_location_matches.csv"
DEFAULT_OUTPUT = SOIL_DATA_DIR / "outputs" / "soil_features_dimension.csv"

IDENTITY_COLUMNS = ["source_areasymbol", "mukey", "muname"]


def read_zip_tables(zip_file: zipfile.ZipFile, root: str, stems: list[str]) -> dict[str, list[dict[str, str]]]:
    inventory = inventory_from_rows(zip_rows(zip_file, f"{root}/tabular/mstab.txt"))
    mstabcol_rows = list(zip_rows(zip_file, f"{root}/tabular/mstabcol.txt"))
    tables: dict[str, list[dict[str, str]]] = {}
    for stem in stems:
        columns = metadata_columns_from_rows(mstabcol_rows, inventory.get(stem, stem))
        rows: list[dict[str, str]] = []
        try:
            for values in zip_rows(zip_file, f"{root}/tabular/{stem}.txt"):
                rows.append({columns[i]: value for i, value in enumerate(values) if i < len(columns)})
        except KeyError:
            pass  # table absent from this survey
        tables[stem] = rows
    return tables


def zip_paths_from_match_file(match_file: Path) -> list[Path]:
    seen: set[Path] = set()
    ordered: list[Path] = []
    with match_file.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row.get("soil_match_status") != "matched":
                continue
            for raw in (row.get("soil_match_zip") or "").split(";"):
                raw = raw.strip()
                if not raw:
                    continue
                path = Path(raw)
                if path not in seen:
                    seen.add(path)
                    ordered.append(path)
    return ordered


def build(zip_paths: list[Path], dictionary_path: Path, output_path: Path) -> tuple[int, int]:
    selected = read_selected_columns(dictionary_path)
    feature_columns: list[str] | None = None
    output_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    handle = output_path.open("w", newline="", encoding="utf-8")
    writer: csv.DictWriter | None = None
    try:
        for index, zip_path in enumerate(zip_paths, start=1):
            if not zip_path.exists():
                print(f"[{index}/{len(zip_paths)}] MISSING {zip_path}", flush=True)
                continue
            with zipfile.ZipFile(zip_path) as zip_file:
                root = survey_root(zip_file)
                tables = read_zip_tables(zip_file, root, REQUIRED_STEMS)
            builder = SoilFeatureBuilder(tables, selected)
            if writer is None:
                feature_columns = builder.feature_columns()
                writer = csv.DictWriter(handle, fieldnames=[*IDENTITY_COLUMNS, *feature_columns], extrasaction="ignore")
                writer.writeheader()

            area = root.upper()
            zip_rows_written = 0
            for mukey in builder.mapunit_by_mukey:
                identity = {"source_areasymbol": area, "mukey": mukey, "muname": builder.muname(mukey)}
                feature_rows = builder.rows_for_mukey(mukey)
                if not feature_rows:
                    writer.writerow(identity)
                    zip_rows_written += 1
                    continue
                for feature_row in feature_rows:
                    writer.writerow({**identity, **feature_row})
                    zip_rows_written += 1
            written += zip_rows_written
            print(f"[{index}/{len(zip_paths)}] {area}: {zip_rows_written} rows", flush=True)
    finally:
        handle.close()
    return written, len(zip_paths)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--match-file", type=Path, default=DEFAULT_MATCH_FILE, help="Plant soil-match CSV; its matched zips define coverage")
    parser.add_argument("--zip", type=Path, action="append", dest="zips", help="Explicit survey zip(s) to include instead of --match-file")
    parser.add_argument("--dictionary", type=Path, default=DEFAULT_DICTIONARY, help="Selected columns dictionary CSV")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Combined dimension CSV")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    zip_paths = args.zips if args.zips else zip_paths_from_match_file(args.match_file)
    written, count = build(zip_paths, args.dictionary, args.output)
    print(f"Wrote {written} (mukey x component x horizon) rows from {count} survey zip(s) to {args.output}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Add the soil map-unit key (soil_match_mukey) to the WQP features table.

Both the soil-match table and the WQP features table are built from the same
public dataset rows, so this aligns them on the unique `SOURCE EXCEL ROW` and
copies `soil_match_mukey` onto the WQP features file. That single foreign key
lets a row reach its soil profile in Soil_data/outputs/soil_features_dimension.csv.

Run this after both pipelines (soil matching and WQP feature merge) have run.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED = REPO_ROOT / "public_data" / "processed_data"
DEFAULT_SOIL = PROCESSED / "report207appendixA_all_tables_labeled_acc_soil_location_matches.csv"
DEFAULT_WQP = PROCESSED / "report207appendixA_all_tables_labeled_acc_wqp_features.csv"
JOIN_KEY = "SOURCE EXCEL ROW"
SOIL_KEY = "soil_match_mukey"


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--soil", type=Path, default=DEFAULT_SOIL, help="Soil location-match CSV")
    parser.add_argument("--wqp", type=Path, default=DEFAULT_WQP, help="WQP features CSV to add the soil key to (updated in place)")
    args = parser.parse_args()

    soil = read_rows(args.soil)
    wqp = read_rows(args.wqp)
    if not soil or not wqp:
        raise ValueError("soil or WQP table is empty")
    for name, rows in (("soil", soil), ("WQP", wqp)):
        if JOIN_KEY not in rows[0]:
            raise ValueError(f"{name} table has no {JOIN_KEY!r} column to join on")

    mukey_by_key = {row.get(JOIN_KEY, ""): row.get(SOIL_KEY, "") for row in soil}
    fieldnames = list(wqp[0].keys())
    if SOIL_KEY not in fieldnames:
        fieldnames.append(SOIL_KEY)

    with args.wqp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in wqp:
            row[SOIL_KEY] = mukey_by_key.get(row.get(JOIN_KEY, ""), "")
            writer.writerow(row)

    populated = sum(1 for row in wqp if mukey_by_key.get(row.get(JOIN_KEY, ""), "").strip())
    print(f"Added {SOIL_KEY} to {args.wqp} ({populated}/{len(wqp)} rows linked to a soil map unit)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

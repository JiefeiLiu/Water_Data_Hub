#!/usr/bin/env python3
"""Print missing-value percentages for columns in a public-data CSV."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "public_data" / "report207appendixA_all_tables_labeled_acc_wqp_features.csv"

DEFAULT_MISSING_VALUES = {
    "",
    "na",
    "n/a",
    "nan",
    "none",
    "null",
}


def parse_missing_values(raw_values: str | None) -> set[str]:
    if raw_values is None:
        return set(DEFAULT_MISSING_VALUES)
    return {value.strip().lower() for value in raw_values.split(",")}


def is_missing(value: str | None, missing_values: set[str]) -> bool:
    if value is None:
        return True
    return value.strip().lower() in missing_values


def read_missingness(input_path: Path, missing_values: set[str]) -> list[dict[str, str]]:
    with input_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{input_path} has no header row")

        fieldnames = reader.fieldnames
        missing_counts = {field: 0 for field in fieldnames}
        total_rows = 0

        for row in reader:
            total_rows += 1
            for field in fieldnames:
                if is_missing(row.get(field), missing_values):
                    missing_counts[field] += 1

    report = []
    for index, field in enumerate(fieldnames):
        missing_count = missing_counts[field]
        missing_percent = (missing_count / total_rows * 100.0) if total_rows else 0.0
        report.append(
            {
                "column": field,
                "missing_count": str(missing_count),
                "total_count": str(total_rows),
                "missing_percent": f"{missing_percent:.2f}",
                "_index": str(index),
            }
        )
    return report


def sort_report(report: list[dict[str, str]], sort_mode: str) -> list[dict[str, str]]:
    if sort_mode == "original":
        return report
    if sort_mode == "name":
        return sorted(report, key=lambda row: row["column"].lower())
    if sort_mode == "missing-asc":
        return sorted(report, key=lambda row: (float(row["missing_percent"]), int(row["_index"])))
    return sorted(report, key=lambda row: (-float(row["missing_percent"]), int(row["_index"])))


def write_report(report: list[dict[str, str]], output_path: Path | None) -> None:
    fieldnames = ["column", "missing_count", "total_count", "missing_percent"]
    rows = [{field: row[field] for field in fieldnames} for row in report]

    if output_path is None:
        writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Public-data CSV to inspect")
    parser.add_argument("--output", type=Path, default=None, help="Optional CSV path for the missingness report")
    parser.add_argument(
        "--sort",
        choices=["missing-desc", "missing-asc", "name", "original"],
        default="missing-desc",
        help="Report sort order",
    )
    parser.add_argument(
        "--missing-values",
        default=None,
        help="Comma-separated values to treat as missing; defaults to empty, NA, N/A, NaN, none, null",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    missing_values = parse_missing_values(args.missing_values)
    report = sort_report(read_missingness(args.input, missing_values), args.sort)
    write_report(report, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Report missing-data percentages for a CSV file."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


DEFAULT_MISSING_VALUES = {
    "",
    "na",
    "n/a",
    "nan",
    "none",
    "null",
    "missing",
}


def is_missing(value: str) -> bool:
    """Return True when a CSV cell should be counted as missing."""
    return value.strip().lower() in DEFAULT_MISSING_VALUES


def analyze_missing_data(csv_path: Path) -> tuple[int, list[dict[str, float | int | str]]]:
    """Return row count and missing-value stats for each column in a CSV file."""
    with csv_path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.reader(file)
        try:
            headers = next(reader)
        except StopIteration as exc:
            raise ValueError(f"{csv_path} is empty.") from exc

        columns = [header.strip() or f"Unnamed column {i + 1}" for i, header in enumerate(headers)]
        missing_counts = [0 for _ in columns]
        row_count = 0

        for row in reader:
            row_count += 1

            if len(row) > len(columns):
                for i in range(len(columns), len(row)):
                    columns.append(f"Extra column {i + 1}")
                    missing_counts.append(row_count - 1)

            for i, _column in enumerate(columns):
                if i >= len(row) or is_missing(row[i]):
                    missing_counts[i] += 1

    report = []
    for column, missing_count in zip(columns, missing_counts):
        percent_missing = (missing_count / row_count * 100) if row_count else 0.0
        report.append(
            {
                "column": column,
                "missing_count": missing_count,
                "total_rows": row_count,
                "percent_missing": percent_missing,
            }
        )

    return row_count, report


def print_report(csv_path: Path, row_count: int, report: list[dict[str, float | int | str]]) -> None:
    total_cells = row_count * len(report)
    total_missing = sum(int(row["missing_count"]) for row in report)
    overall_percent = (total_missing / total_cells * 100) if total_cells else 0.0

    print(f"File: {csv_path}")
    print(f"Rows: {row_count:,}")
    print(f"Columns: {len(report):,}")
    print(f"Overall missing cells: {total_missing:,} of {total_cells:,} ({overall_percent:.2f}%)")
    print()
    print("Missing data by column:")
    print(f"{'Column':<45} {'Missing':>10} {'Total':>10} {'Percent':>10}")
    print("-" * 80)

    for row in sorted(report, key=lambda item: item["percent_missing"], reverse=True):
        column = str(row["column"])
        if len(column) > 45:
            column = column[:42] + "..."

        print(
            f"{column:<45} "
            f"{int(row['missing_count']):>10,} "
            f"{int(row['total_rows']):>10,} "
            f"{float(row['percent_missing']):>9.2f}%"
        )


def save_report(output_path: Path, report: list[dict[str, float | int | str]]) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["column", "missing_count", "total_rows", "percent_missing"],
        )
        writer.writeheader()
        writer.writerows(report)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show the percentage of missing data in a CSV file."
    )
    parser.add_argument(
        "csv_file",
        nargs="?",
        default="Data/1_14_2026.csv",
        help="CSV file to analyze. Default: Data/1_14_2026.csv",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Optional path to save the per-column missing-data report as a CSV.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    csv_path = Path(args.csv_file)

    row_count, report = analyze_missing_data(csv_path)
    print_report(csv_path, row_count, report)

    if args.output:
        output_path = Path(args.output)
        save_report(output_path, report)
        print()
        print(f"Saved report to: {output_path}")


if __name__ == "__main__":
    main()

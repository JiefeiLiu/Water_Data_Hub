#!/usr/bin/env python3
"""Convert every FL071 SSURGO tabular .txt table into a clean CSV.

Unlike the --full-database export, this writes one CSV per tabular table with
the real SSURGO column names only (no source_* tracing columns), so the tables
are easy to skim when deciding which ones are useful for the database. It also
writes a _tables_index.csv summarizing each table's title, description, and
row/column counts.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from ssurgo_full_database import (
    directory_rows,
    fallback_columns,
    inventory_from_rows,
    metadata_columns_from_rows,
)


FL071_DIR = Path(__file__).parent / "FL071"
DEFAULT_OUTPUT_DIR = FL071_DIR / "tabular_csv"


def read_table_descriptions(tabular_dir: Path) -> dict[str, dict[str, str]]:
    """Map physical file stem -> {logical_name, title, description} from mstab.txt."""
    descriptions: dict[str, dict[str, str]] = {}
    for row in directory_rows(tabular_dir / "mstab.txt"):
        # mstab.txt columns: logical_name | short_label | title | description | physical_name
        if len(row) >= 5:
            physical = row[4]
            descriptions[physical] = {
                "logical_name": row[0],
                "title": row[2],
                "description": row[3],
            }
    return descriptions


def columns_by_table(tabular_dir: Path) -> dict[str, list[str]]:
    """Read mstabcol.txt once and return ordered column names for every table."""
    rows = list(directory_rows(tabular_dir / "mstabcol.txt"))
    table_names = {row[0] for row in rows if row}
    return {name: metadata_columns_from_rows(rows, name) for name in table_names}


def convert(base_dir: Path, output_dir: Path) -> list[dict[str, str]]:
    tabular_dir = base_dir / "tabular"
    inventory = inventory_from_rows(directory_rows(tabular_dir / "mstab.txt"))
    descriptions = read_table_descriptions(tabular_dir)
    table_columns = columns_by_table(tabular_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, str]] = []

    for table_path in sorted(tabular_dir.glob("*.txt")):
        stem = table_path.stem
        logical = inventory.get(stem, stem)
        columns = table_columns.get(logical, [])

        rows = directory_rows(table_path)
        first_row = next(rows, None)
        if first_row is not None and not columns:
            columns = fallback_columns(first_row)

        csv_path = output_dir / f"{stem}.csv"
        row_count = 0
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            data_rows = () if first_row is None else _chain_first(first_row, rows)
            for values in data_rows:
                writer.writerow(
                    {columns[i]: value for i, value in enumerate(values) if i < len(columns)}
                )
                row_count += 1

        meta = descriptions.get(stem, {})
        index.append(
            {
                "file_stem": stem,
                "csv_file": csv_path.name,
                "title": meta.get("title", ""),
                "logical_table": logical,
                "rows": str(row_count),
                "columns": str(len(columns)),
                "column_names": ", ".join(columns),
                "description": meta.get("description", ""),
            }
        )

    _write_index(output_dir, index)
    return index


def _chain_first(first_row, rest):
    yield first_row
    yield from rest


def _write_index(output_dir: Path, index: list[dict[str, str]]) -> None:
    index_path = output_dir / "_tables_index.csv"
    fieldnames = ["file_stem", "csv_file", "title", "logical_table", "rows", "columns", "column_names", "description"]
    with index_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(sorted(index, key=lambda item: item["file_stem"]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", type=Path, default=FL071_DIR, help="Path to Soil_data/FL071")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Folder for the CSV files")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    index = convert(args.base_dir, args.output_dir)
    non_empty = sum(1 for item in index if int(item["rows"]) > 0)
    print(f"Converted {len(index)} tabular tables to CSV in {args.output_dir}")
    print(f"  {non_empty} tables have data rows; {len(index) - non_empty} are empty (header only)")
    print(f"  Index: {args.output_dir / '_tables_index.csv'}")


if __name__ == "__main__":
    main()

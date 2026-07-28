#!/usr/bin/env python3
"""Build a readable SSURGO column dictionary from the survey metadata tables.

SSURGO ships its own data dictionary in `tabular/mstabcol.txt` (one row per
column) and the allowed values for coded "Choice" columns in
`tabular/msdomdet.txt`. This script flattens both into a single
`_columns_dictionary.csv` so every feature/column in the tabular CSVs has its
label, data type, units, valid range, coded values, and full description in one
place.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ssurgo_full_database import directory_rows


FL071_DIR = Path(__file__).parent / "FL071"

# Field positions inside tabular/mstabcol.txt (the SSURGO column dictionary).
MSTABCOL = {
    "table": 0,
    "sequence": 1,
    "column_name": 2,
    "logical_name": 3,
    "label": 4,
    "data_type": 5,
    "not_null": 6,
    "field_size": 7,
    "precision": 8,
    "minimum": 9,
    "maximum": 10,
    "units": 11,
    "domain": 12,
    "description": 13,
}

OUTPUT_FIELDS = [
    "table",
    "table_title",
    "sequence",
    "column_name",
    "label",
    "data_type",
    "units",
    "minimum",
    "maximum",
    "domain",
    "allowed_values",
    "description",
]


def read_table_titles(tabular_dir: Path) -> dict[str, str]:
    """Physical table name -> human title, from mstab.txt."""
    titles: dict[str, str] = {}
    for row in directory_rows(tabular_dir / "mstab.txt"):
        if len(row) >= 5:
            titles[row[4]] = row[2]
    return titles


def read_domain_values(tabular_dir: Path) -> dict[str, list[str]]:
    """Domain name -> ordered list of "code: description" allowed values."""
    domain_path = tabular_dir / "msdomdet.txt"
    if not domain_path.exists():
        return {}
    rows: dict[str, list[tuple[int, str]]] = {}
    for row in directory_rows(domain_path):
        # msdomdet.txt columns: domain | sequence | value | value_description | ...
        if len(row) < 3:
            continue
        domain = row[0]
        try:
            sequence = int(row[1])
        except ValueError:
            sequence = len(rows.get(domain, []))
        value = row[2]
        description = row[3].strip() if len(row) > 3 else ""
        label = f"{value}: {description}" if description else value
        rows.setdefault(domain, []).append((sequence, label))
    return {
        domain: [label for _, label in sorted(values)]
        for domain, values in rows.items()
    }


def one_line(value: str) -> str:
    return " ".join(value.split())


def build_dictionary(base_dir: Path) -> list[dict[str, str]]:
    tabular_dir = base_dir / "tabular"
    titles = read_table_titles(tabular_dir)
    domains = read_domain_values(tabular_dir)

    entries: list[dict[str, str]] = []
    for row in directory_rows(tabular_dir / "mstabcol.txt"):
        if len(row) <= MSTABCOL["description"]:
            continue

        def field(name: str) -> str:
            return row[MSTABCOL[name]].strip()

        domain = field("domain")
        allowed = " | ".join(domains.get(domain, [])) if domain else ""
        entries.append(
            {
                "table": field("table"),
                "table_title": titles.get(field("table"), ""),
                "sequence": field("sequence"),
                "column_name": field("column_name"),
                "label": field("label"),
                "data_type": field("data_type"),
                "units": field("units"),
                "minimum": field("minimum"),
                "maximum": field("maximum"),
                "domain": domain,
                "allowed_values": one_line(allowed),
                "description": one_line(field("description")),
            }
        )

    def sort_key(entry: dict[str, str]) -> tuple[str, int]:
        try:
            sequence = int(entry["sequence"])
        except ValueError:
            sequence = 0
        return entry["table"], sequence

    return sorted(entries, key=sort_key)


def write_dictionary(entries: list[dict[str, str]], output_path: Path) -> None:
    import csv

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(entries)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", type=Path, default=FL071_DIR, help="Path to a SSURGO survey folder")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output CSV path (default: <base-dir>/tabular_csv/_columns_dictionary.csv)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = args.output or (args.base_dir / "tabular_csv" / "_columns_dictionary.csv")
    entries = build_dictionary(args.base_dir)
    write_dictionary(entries, output_path)
    tables = len({entry["table"] for entry in entries})
    coded = sum(1 for entry in entries if entry["allowed_values"])
    print(f"Wrote {len(entries)} column definitions across {tables} tables to {output_path}")
    print(f"  {coded} columns have coded allowed-value lists")


if __name__ == "__main__":
    main()

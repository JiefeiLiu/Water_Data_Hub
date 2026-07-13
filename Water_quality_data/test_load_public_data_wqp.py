#!/usr/bin/env python3
"""Quick sanity check for the Water Quality Portal download manifest."""

from __future__ import annotations

import csv
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = DATA_DIR / "public_data_wqp_manifest.csv"
COUNT_SUMMARY_PATH = DATA_DIR / "outputs" / "public_data_wqp_count_summary.csv"


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"Manifest file not found: {MANIFEST_PATH}")

    rows = read_rows(MANIFEST_PATH)
    print(f"Manifest path: {MANIFEST_PATH}")
    print(f"Manifest rows: {len(rows)}")
    print(f"Unique WQP county queries: {len({row['query_url'] for row in rows})}")
    print(f"Statuses: {sorted({row['status'] for row in rows})}")
    print("First 5 rows:")
    for row in rows[:5]:
        print(
            {
                "source_state": row["source_state"],
                "source_county": row["source_county"],
                "matched_county": row["matched_county"],
                "county_code": row["county_code"],
                "total_result_count": row["total_result_count"],
                "status": row["status"],
            }
        )

    if COUNT_SUMMARY_PATH.exists():
        count_rows = read_rows(COUNT_SUMMARY_PATH)
        rows_with_counts = [row for row in count_rows if row.get("total_result_count")]
        print(f"Count summary path: {COUNT_SUMMARY_PATH}")
        print(f"Unique count rows: {len(count_rows)}")
        print(f"Rows with WQP count headers: {len(rows_with_counts)}")
        if rows_with_counts:
            total_results = sum(int(row["total_result_count"] or 0) for row in rows_with_counts)
            print(f"Total result count from WQP headers: {total_results}")


if __name__ == "__main__":
    main()

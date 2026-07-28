#!/usr/bin/env python3
"""Quick sanity check for the combined public-data SSURGO CSV."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


CSV_PATH = Path(__file__).resolve().parent / "outputs" / "public_data_ssurgo_mapunit_centroid_soil_values.csv"


def main() -> None:
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"CSV file not found: {CSV_PATH}")

    df = pd.read_csv(CSV_PATH)
    columns = list(df.columns)

    print(f"CSV path: {CSV_PATH}")
    print(f"Shape: {df.shape}")
    # print(f"Top 10 columns: {columns[:10]}")
    # print("Feature list:")
    # for column in columns:
    #     print(f"- {column}")
    print(df.head())
    print(df.describe())


if __name__ == "__main__":
    main()

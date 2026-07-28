#!/usr/bin/env python3
"""Extract expert-selected SSURGO soil features per map-unit polygon.

For an unpacked survey folder (e.g. CA696) this writes one row per
(polygon x component x horizon) with the columns in Selected_columns_dictionary.csv,
plus two confidence columns:

- polygon_acres: area of the delineation the row describes (SSURGO polygons vary
  enormously in size, so this flags how local a match is).
- component_percent: map-unit percentage (comppct_r) of the component in the row.

For an ID-linked design, prefer build_soil_dimension.py, which emits one row per
(mukey x component x horizon) with no polygon duplication. This per-polygon export
is convenient for exploring a single survey with the delineation geometry attached.
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

from extract_fl071_soil_values import iter_polygon_shapes, read_dbf_records, ring_area_and_centroid, polygon_centroid
from soil_feature_builder import SoilFeatureBuilder, read_selected_columns


SOIL_DATA_DIR = Path(__file__).resolve().parent
DEFAULT_DICTIONARY = SOIL_DATA_DIR / "metadata" / "Selected_columns_dictionary.csv"
WGS84_KM_PER_DEG_LAT = 110.574

LOCATION_COLUMNS = [
    "areasymbol", "mukey", "musym", "muname",
    "polygon_record", "centroid_longitude", "centroid_latitude", "polygon_acres",
]


def read_csv_table(base_dir: Path, stem: str) -> list[dict[str, str]]:
    path = base_dir / "tabular_csv" / f"{stem}.csv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def polygon_acres(rings: list[list[tuple[float, float]]]) -> float:
    if not rings or not rings[0]:
        return 0.0
    mean_lat = sum(point[1] for point in rings[0]) / len(rings[0])
    km_per_deg_lon = 111.320 * math.cos(math.radians(mean_lat))
    area_deg2 = abs(sum(ring_area_and_centroid(ring)[0] for ring in rings))
    return area_deg2 * WGS84_KM_PER_DEG_LAT * km_per_deg_lon * 247.105381


def extract(base_dir: Path, dictionary_path: Path, output_path: Path) -> int:
    area = base_dir.name
    selected = read_selected_columns(dictionary_path)
    from soil_feature_builder import REQUIRED_STEMS

    tables = {stem: read_csv_table(base_dir, stem) for stem in REQUIRED_STEMS}
    builder = SoilFeatureBuilder(tables, selected)

    attributes = read_dbf_records(base_dir / "spatial" / f"soilmu_a_{area.lower()}.dbf")
    shapes = list(iter_polygon_shapes(base_dir / "spatial" / f"soilmu_a_{area.lower()}.shp"))
    if len(attributes) != len(shapes):
        raise ValueError(f"polygon count mismatch: {len(attributes)} dbf records, {len(shapes)} shapes")

    output_columns = [*LOCATION_COLUMNS, *builder.feature_columns()]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_columns, extrasaction="ignore")
        writer.writeheader()
        for attribute, shape in zip(attributes, shapes):
            mukey = attribute.get("mukey", "")
            lon, lat = polygon_centroid(shape["rings"], shape["bbox"])
            location = {
                "areasymbol": attribute.get("areasymbol", ""),
                "mukey": mukey,
                "musym": attribute.get("musym", ""),
                "muname": builder.muname(mukey),
                "polygon_record": shape["record_number"],
                "centroid_longitude": f"{lon:.8f}",
                "centroid_latitude": f"{lat:.8f}",
                "polygon_acres": f"{polygon_acres(shape['rings']):.4f}",
            }
            feature_rows = builder.rows_for_mukey(mukey)
            if not feature_rows:
                writer.writerow(location)
                written += 1
                continue
            for feature_row in feature_rows:
                writer.writerow({**location, **feature_row})
                written += 1
    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", type=Path, required=True, help="SSURGO survey folder (must contain tabular_csv/ and spatial/)")
    parser.add_argument("--dictionary", type=Path, default=DEFAULT_DICTIONARY, help="Selected columns dictionary CSV")
    parser.add_argument("--output", type=Path, default=None, help="Output CSV (default: <base-dir>/outputs/<area>_selected_soil_features.csv)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    area = args.base_dir.name
    output_path = args.output or (args.base_dir / "outputs" / f"{area}_selected_soil_features.csv")
    written = extract(args.base_dir, args.dictionary, output_path)
    print(f"Wrote {written} (polygon x component x horizon) rows to {output_path}")


if __name__ == "__main__":
    main()

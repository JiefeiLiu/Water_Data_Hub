#!/usr/bin/env python3
"""Extract usable FL071 SSURGO soil values with coordinates.

The FL071 export has map-unit polygons and tabular component/horizon data, but
the map-unit point layer has no records. By default this script writes one row
per map-unit polygon using the polygon centroid as the coordinate. If you pass a
CSV of sample/testing points, it assigns each point to the containing map-unit
polygon and appends the representative soil values for that map unit.
"""

from __future__ import annotations

import argparse
import csv
import math
import struct
from pathlib import Path

from ssurgo_full_database import export_directory_full_database


FL071_DIR = Path(__file__).parent / "FL071"
DEFAULT_FULL_DATABASE_DIR = FL071_DIR / "outputs" / "full_database"

VALUE_COLUMNS = [
    "ph1to1h2o_r",
    "ph01mcacl2_r",
    "cec7_r",
    "ecec_r",
    "sumbases_r",
    "caco3_r",
    "gypsum_r",
    "sar_r",
    "pbray1_r",
    "poxalate_r",
    "ph2osoluble_r",
    "ptotal_r",
]


def read_column_names(base_dir: Path, table_name: str) -> list[str]:
    columns: list[tuple[int, str]] = []
    with (base_dir / "tabular" / "mstabcol.txt").open(newline="", encoding="utf-8") as handle:
        for row in csv.reader(handle, delimiter="|", quotechar='"'):
            if row and row[0] == table_name:
                columns.append((int(row[1]), row[2]))
    return [name for _, name in sorted(columns)]


def read_pipe_table(base_dir: Path, file_stem: str, metadata_table: str | None = None) -> list[dict[str, str]]:
    table_name = metadata_table or file_stem
    columns = read_column_names(base_dir, table_name)
    rows: list[dict[str, str]] = []
    with (base_dir / "tabular" / f"{file_stem}.txt").open(newline="", encoding="utf-8") as handle:
        for values in csv.reader(handle, delimiter="|", quotechar='"'):
            rows.append({columns[i]: value for i, value in enumerate(values) if i < len(columns)})
    return rows


def read_dbf_records(path: Path) -> list[dict[str, str]]:
    data = path.read_bytes()
    record_count = struct.unpack("<I", data[4:8])[0]
    header_length = struct.unpack("<H", data[8:10])[0]
    record_length = struct.unpack("<H", data[10:12])[0]

    fields: list[tuple[str, str, int, int]] = []
    offset = 32
    field_offset = 1
    while offset < header_length and data[offset] != 0x0D:
        name = data[offset : offset + 11].split(b"\0", 1)[0].decode("ascii")
        field_type = chr(data[offset + 11])
        field_length = data[offset + 16]
        fields.append((name, field_type, field_offset, field_length))
        field_offset += field_length
        offset += 32

    records: list[dict[str, str]] = []
    for index in range(record_count):
        start = header_length + index * record_length
        record = data[start : start + record_length]
        if not record or record[0:1] == b"*":
            continue
        values: dict[str, str] = {}
        for name, _, field_start, field_length in fields:
            raw_value = record[field_start : field_start + field_length]
            values[name.lower()] = raw_value.decode("latin1").strip()
        records.append(values)
    return records


def iter_polygon_shapes(path: Path):
    data = path.read_bytes()
    offset = 100
    while offset + 8 <= len(data):
        record_number, content_words = struct.unpack(">2i", data[offset : offset + 8])
        offset += 8
        content_length = content_words * 2
        content = data[offset : offset + content_length]
        offset += content_length
        if len(content) < 44:
            continue
        shape_type = struct.unpack("<i", content[:4])[0]
        if shape_type == 0:
            continue
        if shape_type != 5:
            raise ValueError(f"{path} record {record_number} is shape type {shape_type}, expected Polygon")

        bbox = struct.unpack("<4d", content[4:36])
        part_count, point_count = struct.unpack("<2i", content[36:44])
        parts_start = 44
        points_start = parts_start + part_count * 4
        parts = list(struct.unpack(f"<{part_count}i", content[parts_start:points_start]))
        points = [
            struct.unpack("<2d", content[points_start + i * 16 : points_start + (i + 1) * 16])
            for i in range(point_count)
        ]
        rings = []
        for part_index, start in enumerate(parts):
            end = parts[part_index + 1] if part_index + 1 < len(parts) else point_count
            rings.append(points[start:end])
        yield {"record_number": record_number, "bbox": bbox, "rings": rings}


def ring_area_and_centroid(ring: list[tuple[float, float]]) -> tuple[float, float, float]:
    if len(ring) < 3:
        return 0.0, 0.0, 0.0
    twice_area = 0.0
    cx = 0.0
    cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        cross = x0 * y1 - x1 * y0
        twice_area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    area = twice_area / 2.0
    if math.isclose(area, 0.0):
        return 0.0, 0.0, 0.0
    return area, cx / (6.0 * area), cy / (6.0 * area)


def polygon_centroid(rings: list[list[tuple[float, float]]], bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    total_area = 0.0
    weighted_x = 0.0
    weighted_y = 0.0
    for ring in rings:
        area, cx, cy = ring_area_and_centroid(ring)
        total_area += area
        weighted_x += cx * area
        weighted_y += cy * area
    if math.isclose(total_area, 0.0):
        xmin, ymin, xmax, ymax = bbox
        return (xmin + xmax) / 2.0, (ymin + ymax) / 2.0
    return weighted_x / total_area, weighted_y / total_area


def point_in_ring(lon: float, lat: float, ring: list[tuple[float, float]]) -> bool:
    inside = False
    if len(ring) < 3:
        return False
    x_prev, y_prev = ring[-1]
    for x_curr, y_curr in ring:
        crosses = (y_curr > lat) != (y_prev > lat)
        if crosses:
            x_at_lat = (x_prev - x_curr) * (lat - y_curr) / (y_prev - y_curr) + x_curr
            if lon < x_at_lat:
                inside = not inside
        x_prev, y_prev = x_curr, y_curr
    return inside


def point_in_polygon(lon: float, lat: float, rings: list[list[tuple[float, float]]]) -> bool:
    # Even/odd rule across all rings handles multiparts and holes for this use.
    inside = False
    for ring in rings:
        if point_in_ring(lon, lat, ring):
            inside = not inside
    return inside


def to_float(value: str) -> float:
    if value == "":
        return float("-inf")
    try:
        return float(value)
    except ValueError:
        return float("-inf")


def build_soil_lookup(base_dir: Path) -> dict[str, dict[str, str]]:
    mapunits = {row["mukey"]: row for row in read_pipe_table(base_dir, "mapunit")}
    components = read_pipe_table(base_dir, "comp", "component")
    horizons = read_pipe_table(base_dir, "chorizon")

    best_component_by_mukey: dict[str, dict[str, str]] = {}
    for component in components:
        mukey = component.get("mukey", "")
        current = best_component_by_mukey.get(mukey)
        component_score = (
            component.get("majcompflag", "").lower() == "yes",
            to_float(component.get("comppct_r", "")),
        )
        current_score = (
            current.get("majcompflag", "").lower() == "yes",
            to_float(current.get("comppct_r", "")),
        ) if current else (False, float("-inf"))
        if component_score > current_score:
            best_component_by_mukey[mukey] = component

    surface_horizon_by_cokey: dict[str, dict[str, str]] = {}
    for horizon in horizons:
        cokey = horizon.get("cokey", "")
        current = surface_horizon_by_cokey.get(cokey)
        horizon_score = (
            -abs(to_float(horizon.get("hzdept_r", ""))),
            -to_float(horizon.get("hzdepb_r", "")),
        )
        current_score = (
            -abs(to_float(current.get("hzdept_r", ""))),
            -to_float(current.get("hzdepb_r", "")),
        ) if current else (float("-inf"), float("-inf"))
        if horizon_score > current_score:
            surface_horizon_by_cokey[cokey] = horizon

    lookup: dict[str, dict[str, str]] = {}
    for mukey, mapunit in mapunits.items():
        component = best_component_by_mukey.get(mukey, {})
        horizon = surface_horizon_by_cokey.get(component.get("cokey", ""), {})
        values = {
            "musym": mapunit.get("musym", ""),
            "mukey": mukey,
            "muname": mapunit.get("muname", ""),
            "component_name": component.get("compname", ""),
            "component_percent_r": component.get("comppct_r", ""),
            "horizon_name": horizon.get("hzname", ""),
            "horizon_top_cm": horizon.get("hzdept_r", ""),
            "horizon_bottom_cm": horizon.get("hzdepb_r", ""),
        }
        values.update({column: horizon.get(column, "") for column in VALUE_COLUMNS})
        lookup[mukey] = values
    return lookup


def read_polygons(base_dir: Path) -> list[dict[str, object]]:
    attributes = read_dbf_records(base_dir / "spatial" / "soilmu_a_fl071.dbf")
    shapes = list(iter_polygon_shapes(base_dir / "spatial" / "soilmu_a_fl071.shp"))
    if len(attributes) != len(shapes):
        raise ValueError(f"Polygon count mismatch: {len(attributes)} dbf records and {len(shapes)} shapes")

    polygons = []
    for attribute, shape in zip(attributes, shapes):
        lon, lat = polygon_centroid(shape["rings"], shape["bbox"])
        polygons.append(
            {
                "areasymbol": attribute.get("areasymbol", ""),
                "spatialver": attribute.get("spatialver", ""),
                "musym": attribute.get("musym", ""),
                "mukey": attribute.get("mukey", ""),
                "centroid_longitude": lon,
                "centroid_latitude": lat,
                "bbox": shape["bbox"],
                "rings": shape["rings"],
            }
        )
    return polygons


def write_centroid_export(base_dir: Path, output_path: Path) -> int:
    lookup = build_soil_lookup(base_dir)
    polygons = read_polygons(base_dir)
    fieldnames = [
        "areasymbol",
        "spatialver",
        "longitude",
        "latitude",
        "musym",
        "mukey",
        "muname",
        "component_name",
        "component_percent_r",
        "horizon_name",
        "horizon_top_cm",
        "horizon_bottom_cm",
        *VALUE_COLUMNS,
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for polygon in polygons:
            values = lookup.get(str(polygon["mukey"]), {})
            row = {
                "areasymbol": polygon["areasymbol"],
                "spatialver": polygon["spatialver"],
                "longitude": f"{polygon['centroid_longitude']:.8f}",
                "latitude": f"{polygon['centroid_latitude']:.8f}",
                **values,
            }
            writer.writerow(row)
    return len(polygons)


def write_point_export(base_dir: Path, points_csv: Path, lon_column: str, lat_column: str, output_path: Path) -> int:
    lookup = build_soil_lookup(base_dir)
    polygons = read_polygons(base_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with points_csv.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames:
            raise ValueError(f"{points_csv} has no header row")
        if lon_column not in reader.fieldnames or lat_column not in reader.fieldnames:
            raise ValueError(f"Expected columns {lon_column!r} and {lat_column!r} in {points_csv}")

        added_fields = [
            "matched_areasymbol",
            "matched_musym",
            "matched_mukey",
            "muname",
            "component_name",
            "component_percent_r",
            "horizon_name",
            "horizon_top_cm",
            "horizon_bottom_cm",
            *VALUE_COLUMNS,
        ]
        with output_path.open("w", newline="", encoding="utf-8") as target:
            writer = csv.DictWriter(target, fieldnames=[*reader.fieldnames, *added_fields])
            writer.writeheader()
            count = 0
            for row in reader:
                lon = float(row[lon_column])
                lat = float(row[lat_column])
                match = None
                for polygon in polygons:
                    xmin, ymin, xmax, ymax = polygon["bbox"]
                    if xmin <= lon <= xmax and ymin <= lat <= ymax and point_in_polygon(lon, lat, polygon["rings"]):
                        match = polygon
                        break
                if match:
                    values = lookup.get(str(match["mukey"]), {})
                    row.update(
                        {
                            "matched_areasymbol": match["areasymbol"],
                            "matched_musym": match["musym"],
                            "matched_mukey": match["mukey"],
                            **values,
                        }
                    )
                writer.writerow(row)
                count += 1
    return count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", type=Path, default=FL071_DIR, help="Path to Soil_data/FL071")
    parser.add_argument(
        "--full-database",
        action="store_true",
        help="Export every FL071 SSURGO tabular table and spatial DBF attribute table to CSV files",
    )
    parser.add_argument(
        "--full-output-dir",
        type=Path,
        default=DEFAULT_FULL_DATABASE_DIR,
        help="Output directory for --full-database",
    )
    parser.add_argument("--points-csv", type=Path, help="Optional testing-point CSV with longitude/latitude columns")
    parser.add_argument("--lon-column", default="longitude", help="Longitude column in --points-csv")
    parser.add_argument("--lat-column", default="latitude", help="Latitude column in --points-csv")
    parser.add_argument("--replace", action="store_true", help="Replace an existing full database output directory")
    parser.add_argument(
        "--output",
        type=Path,
        default=FL071_DIR / "outputs" / "fl071_mapunit_centroid_soil_values.csv",
        help="Output CSV path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.full_database:
        exported = export_directory_full_database(args.base_dir, args.full_output_dir, args.replace)
        total_rows = sum(item.rows for item in exported)
        print(f"Wrote {len(exported)} full-database CSV tables to {args.full_output_dir}")
        print(f"Total exported rows: {total_rows}")
        print(f"Export manifest: {args.full_output_dir / '_export_manifest.csv'}")
        return

    if args.points_csv:
        count = write_point_export(args.base_dir, args.points_csv, args.lon_column, args.lat_column, args.output)
        print(f"Wrote {count} testing-point rows to {args.output}")
    else:
        count = write_centroid_export(args.base_dir, args.output)
        print(f"Wrote {count} map-unit polygon rows to {args.output}")
    print("Note: FL071 includes pH, CEC, ECEC, sum of bases, CaCO3, gypsum, SAR, and phosphorus fields.")
    print("It does not include separate exchangeable Ca, K, or Mg columns in the SSURGO chorizon table.")


if __name__ == "__main__":
    main()

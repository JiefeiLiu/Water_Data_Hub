#!/usr/bin/env python3
"""Extract representative SSURGO map-unit soil values from downloaded zip files.

This builds the same kind of centroid-level CSV as the FL071 example, but for
the raw SSURGO zip packages listed in public_data_ssurgo_manifest.csv. The zip
files are read directly; they are not permanently unzipped.
"""

from __future__ import annotations

import argparse
import csv
import math
import struct
import sys
import zipfile
from collections.abc import Iterable
from pathlib import Path

from ssurgo_full_database import export_zips_full_database


SOIL_DATA_DIR = Path(__file__).resolve().parent
DEFAULT_MANIFEST = SOIL_DATA_DIR / "metadata" / "public_data_ssurgo_manifest.csv"
DEFAULT_OUTPUT = SOIL_DATA_DIR / "outputs" / "public_data_ssurgo_mapunit_centroid_soil_values.csv"
DEFAULT_ERRORS = SOIL_DATA_DIR / "outputs" / "public_data_ssurgo_processing_errors.csv"
DEFAULT_FULL_DATABASE_DIR = SOIL_DATA_DIR / "outputs" / "public_data_ssurgo_full_database"

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

OUTPUT_COLUMNS = [
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


def read_unique_zip_paths(manifest_path: Path) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    with manifest_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not row.get("local_path"):
                continue
            path = Path(row["local_path"])
            if path not in seen:
                seen.add(path)
                paths.append(path)
    return paths


def zip_text_rows(zip_file: zipfile.ZipFile, member: str) -> Iterable[list[str]]:
    with zip_file.open(member) as raw:
        text = (line.decode("utf-8", errors="replace") for line in raw)
        yield from csv.reader(text, delimiter="|", quotechar='"')


def read_column_names(zip_file: zipfile.ZipFile, root: str, table_name: str) -> list[str]:
    columns: list[tuple[int, str]] = []
    member = f"{root}/tabular/mstabcol.txt"
    for row in zip_text_rows(zip_file, member):
        if row and row[0] == table_name:
            columns.append((int(row[1]), row[2]))
    return [name for _, name in sorted(columns)]


def read_pipe_table(
    zip_file: zipfile.ZipFile,
    root: str,
    file_stem: str,
    metadata_table: str | None = None,
) -> list[dict[str, str]]:
    table_name = metadata_table or file_stem
    columns = read_column_names(zip_file, root, table_name)
    rows: list[dict[str, str]] = []
    member = f"{root}/tabular/{file_stem}.txt"
    for values in zip_text_rows(zip_file, member):
        rows.append({columns[i]: value for i, value in enumerate(values) if i < len(columns)})
    return rows


def read_dbf_records(data: bytes) -> list[dict[str, str]]:
    record_count = struct.unpack("<I", data[4:8])[0]
    header_length = struct.unpack("<H", data[8:10])[0]
    record_length = struct.unpack("<H", data[10:12])[0]

    fields: list[tuple[str, int, int]] = []
    offset = 32
    field_offset = 1
    while offset < header_length and data[offset] != 0x0D:
        name = data[offset : offset + 11].split(b"\0", 1)[0].decode("ascii")
        field_length = data[offset + 16]
        fields.append((name, field_offset, field_length))
        field_offset += field_length
        offset += 32

    records: list[dict[str, str]] = []
    for index in range(record_count):
        start = header_length + index * record_length
        record = data[start : start + record_length]
        if not record or record[0:1] == b"*":
            continue
        values: dict[str, str] = {}
        for name, field_start, field_length in fields:
            raw_value = record[field_start : field_start + field_length]
            values[name.lower()] = raw_value.decode("latin1").strip()
        records.append(values)
    return records


def iter_polygon_shapes(data: bytes):
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
            raise ValueError(f"record {record_number} is shape type {shape_type}, expected Polygon")

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


def polygon_centroid(
    rings: list[list[tuple[float, float]]],
    bbox: tuple[float, float, float, float],
) -> tuple[float, float]:
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


def to_float(value: str) -> float:
    if value == "":
        return float("-inf")
    try:
        return float(value)
    except ValueError:
        return float("-inf")


def build_soil_lookup(zip_file: zipfile.ZipFile, root: str) -> dict[str, dict[str, str]]:
    mapunits = {row["mukey"]: row for row in read_pipe_table(zip_file, root, "mapunit")}
    components = read_pipe_table(zip_file, root, "comp", "component")
    horizons = read_pipe_table(zip_file, root, "chorizon")

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


def survey_root(zip_file: zipfile.ZipFile) -> str:
    roots = {
        name.split("/", 1)[0]
        for name in zip_file.namelist()
        if "/" in name and name.split("/", 1)[0]
    }
    if len(roots) != 1:
        raise ValueError(f"expected one survey root folder, found {sorted(roots)[:5]}")
    return next(iter(roots))


def find_member(zip_file: zipfile.ZipFile, root: str, suffix: str) -> str:
    suffix = suffix.lower()
    for name in zip_file.namelist():
        if name.startswith(f"{root}/") and name.lower().endswith(suffix):
            return name
    raise FileNotFoundError(f"missing {suffix} under {root}")


def write_zip_rows(zip_path: Path, writer: csv.DictWriter) -> int:
    with zipfile.ZipFile(zip_path) as zip_file:
        root = survey_root(zip_file)
        area = root.lower()
        dbf_member = find_member(zip_file, root, f"/spatial/soilmu_a_{area}.dbf")
        shp_member = find_member(zip_file, root, f"/spatial/soilmu_a_{area}.shp")

        lookup = build_soil_lookup(zip_file, root)
        attributes = read_dbf_records(zip_file.read(dbf_member))
        shapes = list(iter_polygon_shapes(zip_file.read(shp_member)))
        if len(attributes) != len(shapes):
            raise ValueError(f"polygon count mismatch: {len(attributes)} dbf records and {len(shapes)} shapes")

        count = 0
        for attribute, shape in zip(attributes, shapes):
            lon, lat = polygon_centroid(shape["rings"], shape["bbox"])
            values = lookup.get(attribute.get("mukey", ""), {})
            writer.writerow(
                {
                    "areasymbol": attribute.get("areasymbol", ""),
                    "spatialver": attribute.get("spatialver", ""),
                    "longitude": f"{lon:.8f}",
                    "latitude": f"{lat:.8f}",
                    **values,
                }
            )
            count += 1
        return count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="SSURGO download manifest CSV")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Combined processed output CSV")
    parser.add_argument("--errors", type=Path, default=DEFAULT_ERRORS, help="Processing error CSV")
    parser.add_argument(
        "--full-database",
        action="store_true",
        help="Export every SSURGO tabular table and spatial DBF attribute table from all downloaded zips",
    )
    parser.add_argument(
        "--full-output-dir",
        type=Path,
        default=DEFAULT_FULL_DATABASE_DIR,
        help="Output directory for --full-database",
    )
    parser.add_argument("--limit", type=int, help="Process only the first N unique zip files")
    parser.add_argument("--replace", action="store_true", help="Overwrite an existing output CSV")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists() and not args.replace:
        print(f"Refusing to overwrite existing output without --replace: {args.output}", file=sys.stderr)
        return 2

    zip_paths = read_unique_zip_paths(args.manifest)
    if args.limit:
        zip_paths = zip_paths[: args.limit]
    missing = [path for path in zip_paths if not path.exists()]
    if missing:
        print(f"Missing {len(missing)} zip files; first missing file: {missing[0]}", file=sys.stderr)
        return 1

    if args.full_database:
        exported = export_zips_full_database(zip_paths, args.full_output_dir, args.replace)
        total_rows = sum(item.rows for item in exported)
        print(f"Wrote {len(exported)} full-database CSV tables to {args.full_output_dir}")
        print(f"Total exported rows: {total_rows}")
        print(f"Export manifest: {args.full_output_dir / '_export_manifest.csv'}")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.errors.parent.mkdir(parents=True, exist_ok=True)

    total_rows = 0
    errors: list[dict[str, str]] = []
    partial_output = args.output.with_name(f"{args.output.name}.partial")
    with partial_output.open("w", newline="", encoding="utf-8") as output_handle:
        writer = csv.DictWriter(output_handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for index, zip_path in enumerate(zip_paths, start=1):
            print(f"[{index}/{len(zip_paths)}] Processing {zip_path.parent.name}: {zip_path.name}", flush=True)
            try:
                rows = write_zip_rows(zip_path, writer)
            except Exception as exc:  # Continue so one bad archive does not hide later issues.
                errors.append({"zip_path": str(zip_path), "error": str(exc)})
                print(f"  ERROR: {exc}", flush=True)
                continue
            total_rows += rows
            print(f"  wrote {rows} rows", flush=True)

    partial_output.replace(args.output)

    with args.errors.open("w", newline="", encoding="utf-8") as error_handle:
        writer = csv.DictWriter(error_handle, fieldnames=["zip_path", "error"])
        writer.writeheader()
        writer.writerows(errors)

    print(f"Wrote {total_rows} map-unit polygon rows to {args.output}")
    print(f"Processing errors: {len(errors)}")
    print(f"Errors CSV: {args.errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

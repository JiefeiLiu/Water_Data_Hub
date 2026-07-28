#!/usr/bin/env python3
"""Test-match public dataset coordinates to downloaded SSURGO locations.

This script does not merge soil features. It only appends location-match
metadata to the public dataset:

1. Try to find the SSURGO map-unit polygon containing each coordinate.
2. If no containing polygon is found, fall back to the nearest map-unit polygon
   centroid within a configurable maximum distance.
3. If no candidate is close enough, mark the row as no match.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import struct
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOIL_DATA_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = REPO_ROOT / "public_data" / "metadata" / "report207appendixA_all_tables_labeled_acc.csv"
DEFAULT_OUTPUT = REPO_ROOT / "public_data" / "processed_data" / "report207appendixA_all_tables_labeled_acc_soil_location_matches.csv"
DEFAULT_MANIFEST = SOIL_DATA_DIR / "metadata" / "public_data_ssurgo_manifest.csv"

MATCH_COLUMNS = [
    "soil_match_status",
    "soil_match_method",
    "soil_match_distance_km",
    "soil_match_area_symbol",
    "soil_match_folder",
    "soil_match_zip",
    "soil_match_mukey",
    "soil_match_musym",
    "soil_match_longitude",
    "soil_match_latitude",
    "soil_match_polygon_acres",
    "soil_match_note",
]


@dataclass(frozen=True)
class CandidateZip:
    area_symbol: str
    zip_path: Path
    source_state: str
    source_county: str


@dataclass
class PointRow:
    index: int
    latitude: float
    longitude: float
    group_key: tuple[Path, ...]


@dataclass
class MatchResult:
    status: str
    method: str
    distance_km: str = ""
    area_symbol: str = ""
    folder: str = ""
    zip_path: str = ""
    mukey: str = ""
    musym: str = ""
    longitude: str = ""
    latitude: str = ""
    polygon_acres: str = ""
    note: str = ""

    def as_row(self) -> dict[str, str]:
        return {
            "soil_match_status": self.status,
            "soil_match_method": self.method,
            "soil_match_distance_km": self.distance_km,
            "soil_match_area_symbol": self.area_symbol,
            "soil_match_folder": self.folder,
            "soil_match_zip": self.zip_path,
            "soil_match_mukey": self.mukey,
            "soil_match_musym": self.musym,
            "soil_match_longitude": self.longitude,
            "soil_match_latitude": self.latitude,
            "soil_match_polygon_acres": self.polygon_acres,
            "soil_match_note": self.note,
        }


def normalize_name(value: str) -> str:
    value = value.lower().replace("saint", "st")
    return re.sub(r"[^a-z0-9]", "", value)


def county_tokens(raw_county: str) -> list[str]:
    county = (raw_county or "").strip()
    if not county or county.lower() == "none":
        return ["none"]
    return [part.strip() for part in re.split(r"\s*(?:&|/|;|\band\b)\s*", county, flags=re.IGNORECASE) if part.strip()]


def search_keys(state: str, county: str) -> list[tuple[str, str]]:
    state = state.strip().upper()
    keys = []
    for county_token in county_tokens(county):
        county_key = "none" if county_token.lower() == "none" else normalize_name(county_token)
        keys.append((state, county_key))
    return keys


def read_manifest_candidates(manifest_path: Path) -> dict[tuple[str, str], list[CandidateZip]]:
    candidates: dict[tuple[str, str], list[CandidateZip]] = defaultdict(list)
    seen: set[tuple[tuple[str, str], Path]] = set()
    with manifest_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            local_path = (row.get("local_path") or "").strip()
            if not local_path:
                continue
            state = (row.get("source_state") or "").strip().upper()
            source_county = (row.get("source_county") or "none").strip()
            matched_county = (row.get("matched_county") or "").strip()
            keys = {(state, "none" if source_county.lower() == "none" else normalize_name(source_county))}
            if matched_county:
                keys.add((state, normalize_name(matched_county)))
            candidate = CandidateZip(
                area_symbol=(row.get("area_symbol") or "").strip(),
                zip_path=Path(local_path),
                source_state=state,
                source_county=source_county,
            )
            for key in keys:
                marker = (key, candidate.zip_path)
                if marker in seen:
                    continue
                seen.add(marker)
                candidates[key].append(candidate)
    return candidates


def parse_float(value: str) -> float | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def read_dbf_records(data: bytes) -> list[dict[str, str]]:
    record_count = struct.unpack("<I", data[4:8])[0]
    header_length = struct.unpack("<H", data[8:10])[0]
    record_length = struct.unpack("<H", data[10:12])[0]

    fields: list[tuple[str, int, int]] = []
    offset = 32
    field_offset = 1
    while offset < header_length and data[offset] != 0x0D:
        name = data[offset : offset + 11].split(b"\0", 1)[0].decode("ascii").lower()
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
            values[name] = raw_value.decode("latin1").strip()
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
        yield {"bbox": bbox, "rings": rings}


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
    inside = False
    for ring in rings:
        if point_in_ring(lon, lat, ring):
            inside = not inside
    return inside


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    radius_km = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius_km * math.asin(math.sqrt(a))


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


def polygon_acres(rings: list[list[tuple[float, float]]]) -> float:
    if not rings or not rings[0]:
        return 0.0
    mean_lat = sum(point[1] for point in rings[0]) / len(rings[0])
    km_per_deg_lon = 111.320 * math.cos(math.radians(mean_lat))
    area_deg2 = abs(sum(ring_area_and_centroid(ring)[0] for ring in rings))
    return area_deg2 * 110.574 * km_per_deg_lon * 247.105381


def iter_zip_polygons(candidate: CandidateZip):
    with zipfile.ZipFile(candidate.zip_path) as zip_file:
        root = survey_root(zip_file)
        area = root.lower()
        dbf_member = find_member(zip_file, root, f"/spatial/soilmu_a_{area}.dbf")
        shp_member = find_member(zip_file, root, f"/spatial/soilmu_a_{area}.shp")
        attributes = read_dbf_records(zip_file.read(dbf_member))
        shapes = iter_polygon_shapes(zip_file.read(shp_member))
        for attribute, shape in zip(attributes, shapes):
            centroid_lon, centroid_lat = polygon_centroid(shape["rings"], shape["bbox"])
            yield attribute, shape, centroid_lon, centroid_lat


def format_match(
    method: str,
    candidate: CandidateZip,
    attribute: dict[str, str],
    centroid_lon: float,
    centroid_lat: float,
    distance_km: float,
    acres: float,
    note: str,
) -> MatchResult:
    return MatchResult(
        status="matched",
        method=method,
        distance_km=f"{distance_km:.6f}",
        area_symbol=candidate.area_symbol,
        folder=candidate.zip_path.parent.name,
        zip_path=str(candidate.zip_path),
        mukey=attribute.get("mukey", ""),
        musym=attribute.get("musym", ""),
        longitude=f"{centroid_lon:.8f}",
        latitude=f"{centroid_lat:.8f}",
        polygon_acres=f"{acres:.4f}",
        note=note,
    )


def match_group(
    points: list[PointRow],
    candidates: list[CandidateZip],
    max_nearest_km: float,
) -> dict[int, MatchResult]:
    results: dict[int, MatchResult] = {}
    nearest: dict[int, tuple[float, CandidateZip, dict[str, str], float, float, float]] = {}

    for candidate_index, candidate in enumerate(candidates, start=1):
        print(
            f"  candidate {candidate_index}/{len(candidates)} {candidate.area_symbol}",
            flush=True,
        )
        for attribute, shape, centroid_lon, centroid_lat in iter_zip_polygons(candidate):
            xmin, ymin, xmax, ymax = shape["bbox"]
            for point in points:
                if point.index in results:
                    continue
                if xmin <= point.longitude <= xmax and ymin <= point.latitude <= ymax:
                    if point_in_polygon(point.longitude, point.latitude, shape["rings"]):
                        results[point.index] = format_match(
                            method="polygon_contains",
                            candidate=candidate,
                            attribute=attribute,
                            centroid_lon=centroid_lon,
                            centroid_lat=centroid_lat,
                            distance_km=0.0,
                            acres=polygon_acres(shape["rings"]),
                            note="sample coordinate falls inside this SSURGO map-unit polygon",
                        )
                        continue

                distance_km = haversine_km(point.longitude, point.latitude, centroid_lon, centroid_lat)
                current = nearest.get(point.index)
                if current is None or distance_km < current[0]:
                    nearest[point.index] = (distance_km, candidate, attribute, centroid_lon, centroid_lat, polygon_acres(shape["rings"]))

    for point in points:
        if point.index in results:
            continue
        current = nearest.get(point.index)
        if current is None:
            results[point.index] = MatchResult(
                status="no_match",
                method="no_soil_polygons_checked",
                note="no candidate SSURGO polygons were available",
            )
            continue
        distance_km, candidate, attribute, centroid_lon, centroid_lat, acres = current
        if distance_km <= max_nearest_km:
            results[point.index] = format_match(
                method="nearest_centroid",
                candidate=candidate,
                attribute=attribute,
                centroid_lon=centroid_lon,
                centroid_lat=centroid_lat,
                distance_km=distance_km,
                acres=acres,
                note=f"no containing polygon found; nearest centroid within {max_nearest_km:g} km",
            )
        else:
            results[point.index] = MatchResult(
                status="no_match",
                method="nearest_centroid_too_far",
                distance_km=f"{distance_km:.6f}",
                area_symbol=candidate.area_symbol,
                folder=candidate.zip_path.parent.name,
                zip_path=str(candidate.zip_path),
                mukey=attribute.get("mukey", ""),
                musym=attribute.get("musym", ""),
                longitude=f"{centroid_lon:.8f}",
                latitude=f"{centroid_lat:.8f}",
                polygon_acres=f"{acres:.4f}",
                note=f"nearest centroid is farther than max distance {max_nearest_km:g} km",
            )
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Public data CSV with coordinates")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output CSV with appended match columns")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="SSURGO download manifest")
    parser.add_argument("--lat-column", default="ACC_X", help="Latitude column in --input")
    parser.add_argument("--lon-column", default="ACC_Y", help="Longitude column in --input")
    parser.add_argument("--max-nearest-km", type=float, default=10.0, help="Maximum nearest-centroid fallback distance")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    candidates_by_key = read_manifest_candidates(args.manifest)
    with args.input.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{args.input} has no header row")
        rows = list(reader)
        input_fields = reader.fieldnames

    results: dict[int, MatchResult] = {}
    groups: dict[tuple[Path, ...], list[PointRow]] = defaultdict(list)
    group_candidates: dict[tuple[Path, ...], list[CandidateZip]] = {}

    for index, row in enumerate(rows):
        lat = parse_float(row.get(args.lat_column, ""))
        lon = parse_float(row.get(args.lon_column, ""))
        if lat is None or lon is None:
            results[index] = MatchResult(
                status="skipped",
                method="missing_coordinates",
                note=f"missing {args.lat_column} or {args.lon_column}",
            )
            continue

        candidates: list[CandidateZip] = []
        seen_paths: set[Path] = set()
        for key in search_keys(row.get("STATE", ""), row.get("COUNTY", "")):
            for candidate in candidates_by_key.get(key, []):
                if candidate.zip_path in seen_paths:
                    continue
                seen_paths.add(candidate.zip_path)
                candidates.append(candidate)

        if not candidates:
            results[index] = MatchResult(
                status="no_match",
                method="no_candidate_soil_files",
                note="no downloaded SSURGO files found for this state/county search",
            )
            continue

        group_key = tuple(candidate.zip_path for candidate in candidates)
        group_candidates[group_key] = candidates
        groups[group_key].append(PointRow(index=index, latitude=lat, longitude=lon, group_key=group_key))

    for group_index, (group_key, points) in enumerate(groups.items(), start=1):
        candidates = group_candidates[group_key]
        print(
            f"[{group_index}/{len(groups)}] Matching {len(points)} row(s) against {len(candidates)} candidate SSURGO zip(s)",
            flush=True,
        )
        results.update(match_group(points, candidates, args.max_nearest_km))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[*input_fields, *MATCH_COLUMNS])
        writer.writeheader()
        for index, row in enumerate(rows):
            result = results[index]
            writer.writerow({**row, **result.as_row()})

    counts: dict[str, int] = defaultdict(int)
    for result in results.values():
        counts[f"{result.status}:{result.method}"] += 1

    print(f"Wrote {len(rows)} rows to {args.output}", flush=True)
    for key in sorted(counts):
        print(f"{key}: {counts[key]}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

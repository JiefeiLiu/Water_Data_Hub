#!/usr/bin/env python3
"""Utilities for exporting SSURGO tabular and spatial DBF data to CSV files."""

from __future__ import annotations

import csv
import shutil
import struct
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import chain
from pathlib import Path


csv.field_size_limit(10_000_000)


@dataclass
class ExportedTable:
    category: str
    name: str
    path: Path
    rows: int
    columns: int


class CsvCollectionWriter:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.handles = {}
        self.writers = {}
        self.columns = {}
        self.row_counts = {}

    def writer(self, category: str, name: str, columns: list[str]) -> csv.DictWriter:
        key = (category, name)
        if key in self.writers:
            if self.columns[key] != columns:
                raise ValueError(f"Column mismatch for {category}/{name}")
            return self.writers[key]

        path = self.output_dir / category / f"{name}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("w", newline="", encoding="utf-8")
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        self.handles[key] = handle
        self.writers[key] = writer
        self.columns[key] = columns
        self.row_counts[key] = 0
        return writer

    def write_row(self, category: str, name: str, columns: list[str], row: dict[str, str]) -> None:
        writer = self.writer(category, name, columns)
        writer.writerow(row)
        self.row_counts[(category, name)] += 1

    def ensure_table(self, category: str, name: str, columns: list[str]) -> None:
        self.writer(category, name, columns)

    def close(self) -> list[ExportedTable]:
        exported = []
        for key, handle in self.handles.items():
            handle.close()
            category, name = key
            exported.append(
                ExportedTable(
                    category=category,
                    name=name,
                    path=self.output_dir / category / f"{name}.csv",
                    rows=self.row_counts[key],
                    columns=len(self.columns[key]),
                )
            )
        return sorted(exported, key=lambda item: (item.category, item.name))


def prepare_output_dir(output_dir: Path, replace: bool) -> None:
    if output_dir.exists():
        if not replace:
            raise FileExistsError(f"Output directory already exists; pass --replace to overwrite: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def write_export_manifest(output_dir: Path, exported: list[ExportedTable]) -> None:
    path = output_dir / "_export_manifest.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["category", "name", "path", "rows", "columns"])
        writer.writeheader()
        for item in exported:
            writer.writerow(
                {
                    "category": item.category,
                    "name": item.name,
                    "path": str(item.path),
                    "rows": item.rows,
                    "columns": item.columns,
                }
            )


def read_dbf_fields_and_records(data: bytes) -> tuple[list[str], list[dict[str, str]]]:
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
    return [field[0] for field in fields], records


def directory_rows(path: Path) -> Iterable[list[str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        yield from csv.reader(handle, delimiter="|", quotechar='"')


def zip_rows(zip_file: zipfile.ZipFile, member: str) -> Iterable[list[str]]:
    with zip_file.open(member) as raw:
        text = (line.decode("utf-8", errors="replace") for line in raw)
        yield from csv.reader(text, delimiter="|", quotechar='"')


def metadata_columns_from_rows(rows: Iterable[list[str]], table_name: str) -> list[str]:
    columns: list[tuple[int, str]] = []
    for row in rows:
        if row and row[0] == table_name:
            columns.append((int(row[1]), row[2]))
    return [name for _, name in sorted(columns)]


def inventory_from_rows(rows: Iterable[list[str]]) -> dict[str, str]:
    inventory = {}
    for row in rows:
        if len(row) >= 5:
            table_name = row[0]
            physical_name = row[4]
            inventory[physical_name] = table_name
    return inventory


def fallback_columns(first_row: list[str]) -> list[str]:
    return [f"field_{index}" for index in range(1, len(first_row) + 1)]


def spatial_layer_name(file_stem: str, survey_root: str) -> str:
    suffix = f"_{survey_root.lower()}"
    if file_stem.lower().endswith(suffix):
        return file_stem[: -len(suffix)]
    return file_stem


def export_directory_full_database(base_dir: Path, output_dir: Path, replace: bool = False) -> list[ExportedTable]:
    prepare_output_dir(output_dir, replace)
    writer = CsvCollectionWriter(output_dir)
    source_area = base_dir.name.upper()
    source_path = str(base_dir)
    inventory = inventory_from_rows(directory_rows(base_dir / "tabular" / "mstab.txt"))

    for table_path in sorted((base_dir / "tabular").glob("*.txt")):
        stem = table_path.stem
        table_name = inventory.get(stem, stem)
        columns = metadata_columns_from_rows(directory_rows(base_dir / "tabular" / "mstabcol.txt"), table_name)
        rows = directory_rows(table_path)
        first_row = next(rows, None)
        if first_row is None:
            if not columns:
                columns = []
            writer.ensure_table("tabular", stem, ["source_areasymbol", "source_path", "survey_root", *columns])
            continue
        if not columns:
            columns = fallback_columns(first_row)
        output_columns = ["source_areasymbol", "source_path", "survey_root", *columns]
        for values in chain([first_row], rows):
            row = {
                "source_areasymbol": source_area,
                "source_path": source_path,
                "survey_root": base_dir.name,
            }
            row.update({columns[index]: value for index, value in enumerate(values) if index < len(columns)})
            writer.write_row("tabular", stem, output_columns, row)

    for dbf_path in sorted((base_dir / "spatial").glob("*.dbf")):
        fields, records = read_dbf_fields_and_records(dbf_path.read_bytes())
        layer = spatial_layer_name(dbf_path.stem, base_dir.name)
        output_columns = [
            "source_areasymbol",
            "source_path",
            "survey_root",
            "spatial_file",
            "record_index",
            *fields,
        ]
        writer.ensure_table("spatial", layer, output_columns)
        for index, record in enumerate(records, start=1):
            row = {
                "source_areasymbol": source_area,
                "source_path": source_path,
                "survey_root": base_dir.name,
                "spatial_file": dbf_path.name,
                "record_index": str(index),
            }
            row.update(record)
            writer.write_row("spatial", layer, output_columns, row)

    exported = writer.close()
    write_export_manifest(output_dir, exported)
    return exported


def survey_root(zip_file: zipfile.ZipFile) -> str:
    roots = {
        name.split("/", 1)[0]
        for name in zip_file.namelist()
        if "/" in name and name.split("/", 1)[0]
    }
    if len(roots) != 1:
        raise ValueError(f"expected one survey root folder, found {sorted(roots)[:5]}")
    return next(iter(roots))


def export_zip_full_database(zip_path: Path, writer: CsvCollectionWriter) -> int:
    file_count = 0
    with zipfile.ZipFile(zip_path) as zip_file:
        root = survey_root(zip_file)
        source_area = root.upper()
        source_path = str(zip_path)
        inventory = inventory_from_rows(zip_rows(zip_file, f"{root}/tabular/mstab.txt"))

        tabular_members = [
            member
            for member in zip_file.namelist()
            if member.startswith(f"{root}/tabular/") and member.lower().endswith(".txt")
        ]
        for member in sorted(tabular_members):
            stem = Path(member).stem
            table_name = inventory.get(stem, stem)
            columns = metadata_columns_from_rows(zip_rows(zip_file, f"{root}/tabular/mstabcol.txt"), table_name)
            rows = zip_rows(zip_file, member)
            first_row = next(rows, None)
            if first_row is None:
                if not columns:
                    columns = []
                writer.ensure_table("tabular", stem, ["source_areasymbol", "source_path", "survey_root", *columns])
                file_count += 1
                continue
            if not columns:
                columns = fallback_columns(first_row)
            output_columns = ["source_areasymbol", "source_path", "survey_root", *columns]
            for values in chain([first_row], rows):
                row = {
                    "source_areasymbol": source_area,
                    "source_path": source_path,
                    "survey_root": root,
                }
                row.update({columns[index]: value for index, value in enumerate(values) if index < len(columns)})
                writer.write_row("tabular", stem, output_columns, row)
            file_count += 1

        spatial_members = [
            member
            for member in zip_file.namelist()
            if member.startswith(f"{root}/spatial/") and member.lower().endswith(".dbf")
        ]
        for member in sorted(spatial_members):
            fields, records = read_dbf_fields_and_records(zip_file.read(member))
            layer = spatial_layer_name(Path(member).stem, root)
            output_columns = [
                "source_areasymbol",
                "source_path",
                "survey_root",
                "spatial_file",
                "record_index",
                *fields,
            ]
            writer.ensure_table("spatial", layer, output_columns)
            for index, record in enumerate(records, start=1):
                row = {
                    "source_areasymbol": source_area,
                    "source_path": source_path,
                    "survey_root": root,
                    "spatial_file": Path(member).name,
                    "record_index": str(index),
                }
                row.update(record)
                writer.write_row("spatial", layer, output_columns, row)
            file_count += 1
    return file_count


def export_zips_full_database(zip_paths: list[Path], output_dir: Path, replace: bool = False) -> list[ExportedTable]:
    prepare_output_dir(output_dir, replace)
    writer = CsvCollectionWriter(output_dir)
    for index, zip_path in enumerate(zip_paths, start=1):
        print(f"[{index}/{len(zip_paths)}] Exporting full database from {zip_path.parent.name}: {zip_path.name}", flush=True)
        file_count = export_zip_full_database(zip_path, writer)
        print(f"  exported {file_count} tabular/spatial DBF files", flush=True)
    exported = writer.close()
    write_export_manifest(output_dir, exported)
    return exported

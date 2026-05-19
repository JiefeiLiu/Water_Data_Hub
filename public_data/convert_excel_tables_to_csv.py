#!/usr/bin/env python3
"""Convert every table-like range in an XLSX workbook to CSV files.

This script intentionally uses only the Python standard library. It first
looks for formal Excel Table ranges. If the workbook does not define formal
tables, it falls back to detecting repeated worksheet sections, which works for
workbooks where several tables are laid out manually on one sheet.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from posixpath import dirname, join, normpath
from zipfile import ZipFile


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

NS = {
    "m": MAIN_NS,
    "r": REL_NS,
}


@dataclass(frozen=True)
class SheetData:
    name: str
    part: str
    rows: dict[int, dict[int, str]]


@dataclass(frozen=True)
class TableRange:
    sheet_name: str
    name: str
    start_row: int
    end_row: int
    start_col: int
    end_col: int


STANDARD_COLUMNS = [
    "STATE",
    "COUNTY",
    "NAME",
    "OWNER",
    "CITY",
    "TYPE",
    "PURPOSE",
    "MGD MAX",
    "START DESAL",
    "DISPOSAL CONCENTRATE",
    "WATER SOURCE",
    "DESAL REASON / TREATMENT",
    "CONCENTRATE POST-TREATMENT",
    "DESAL DESIGN PRODUCTION (mgd)",
    "DESAL AVERAGE PRODUCTION (mgd)",
    "PLANT DESIGN PRODUCTION (mgd)",
    "PLANT AVERAGE PRODUCTION (mgd)",
    "BLENDING?",
    "RAW WATER TDS OR CONDUCTIVITY",
    "PRE-TREATMENT",
    "FEED PRESSURE TO DESAL (psi)",
    "MEMBRANE RECOVERY (%)",
    "PERMEATE TDS OR CONDUCTIVITY",
    "BLEND TDS OR CONDUCTIVITY",
    "BLEND RATIO (PERMEATE : OTHER)",
    "BLEND WATER SOURCE",
    "PERMEATE POST-TREATMENT",
    "AGE OF MEMBRANE / LAST REPLACEMENT (yr)",
    "FATE OF WASTEWATER CLEANING",
    "FATE OF WASTE BACKWASH",
    "SOURCE SECTION",
    "SOURCE EXCEL ROW",
]

SOURCE_COLUMN_BY_OUTPUT_COLUMN = {
    "STATE": 1,
    "COUNTY": 2,
    "NAME": 3,
    "OWNER": 4,
    "CITY": 5,
    "TYPE": 6,
    "PURPOSE": 7,
    "MGD MAX": 8,
    "START DESAL": 9,
    "DISPOSAL CONCENTRATE": 10,
    "WATER SOURCE": 11,
    "DESAL REASON / TREATMENT": 12,
    "CONCENTRATE POST-TREATMENT": 14,
    "DESAL DESIGN PRODUCTION (mgd)": 15,
    "DESAL AVERAGE PRODUCTION (mgd)": 16,
    "PLANT DESIGN PRODUCTION (mgd)": 17,
    "PLANT AVERAGE PRODUCTION (mgd)": 18,
    "BLENDING?": 19,
    "RAW WATER TDS OR CONDUCTIVITY": 20,
    "PRE-TREATMENT": 21,
    "FEED PRESSURE TO DESAL (psi)": 22,
    "MEMBRANE RECOVERY (%)": 23,
    "PERMEATE TDS OR CONDUCTIVITY": 24,
    "BLEND TDS OR CONDUCTIVITY": 25,
    "BLEND RATIO (PERMEATE : OTHER)": 26,
    "BLEND WATER SOURCE": 27,
    "PERMEATE POST-TREATMENT": 28,
    "AGE OF MEMBRANE / LAST REPLACEMENT (yr)": 29,
    "FATE OF WASTEWATER CLEANING": 30,
    "FATE OF WASTE BACKWASH": 31,
}

STATE_BY_SECTION_KEYWORD = {
    "FLORIDA": "FL",
    "CALIFORNIA": "CA",
    "TEXAS": "TX",
}

VALUE_EXPANSIONS = {
    "TYPE": {
        "RO": "Reverse osmosis",
        "NF": "Nanofiltration",
        "MF/RO": "Microfiltration / reverse osmosis",
        "UF/RO": "Ultrafiltration / reverse osmosis",
        "SWRO": "Seawater reverse osmosis",
        "primarily EDR (EDR/MF/RO/evap)": (
            "primarily electrodialysis reversal "
            "(electrodialysis reversal / microfiltration / reverse osmosis / evaporation)"
        ),
        "MF/RO/AOP": "Microfiltration / reverse osmosis / advanced oxidation process",
        "RO/VSEP": "Reverse osmosis / vibratory shear enhanced processing",
        "UF/NF and NF (separate systems)": (
            "Ultrafiltration / nanofiltration and nanofiltration (separate systems)"
        ),
        "UF/NF": "Ultrafiltration / nanofiltration",
    },
    "PURPOSE": {
        "DW": "Drinking water",
        "WWTP": "Wastewater treatment plant",
        "WRF": "Water reclamation facility",
        "ATP (advanced treatment plant)": "Advanced treatment plant",
    },
    "WATER SOURCE": {
        "GW": "Groundwater",
        "surface": "Surface water",
        "surface (lake)": "Surface water (lake)",
        "surface and GW": "Surface water and groundwater",
        "ocean": "Seawater",
        "WWTP": "Wastewater treatment plant",
    },
    "DISPOSAL CONCENTRATE": {
        "surface": "Surface water discharge",
        "sewer": "Sewer discharge",
        "DWI": "Deep well injection",
        "EP": "Evaporation pond",
        "LA": "Land application",
        "outfall": "Outfall",
        "DWI/sewer": "Deep well injection / sewer discharge",
        "EP and sewer": "Evaporation pond and sewer discharge",
        "surface (lake)": "Surface water discharge (lake)",
        "surface (to Great Salt Lake)": "Surface water discharge (to Great Salt Lake)",
    },
    "FATE OF WASTEWATER CLEANING": {
        "DWI": "Deep well injection",
        "DWI (haven't cleaned yet)": "Deep well injection (haven't cleaned yet)",
        "neutralize, DWI": "neutralization, deep well injection",
    },
}

TEXT_REPLACEMENTS = {
    "DISPOSAL CONCENTRATE": [
        (r"\b(?-i:LA)(?=\s+sanitation\b)", "Los Angeles"),
        (r"^LA(?=\s*\()", "Land application"),
        (r"\b(?-i:DWI)\b", "Deep well injection"),
        (r"\b(?-i:WWTP)\b", "wastewater treatment plant"),
        (r"\b(?-i:OCSD)\b", "Orange County Sanitation District"),
        (r"\b(?-i:OO)\b", "ocean outfall"),
        (r"\b(?-i:OF)\b", "outfall"),
        (r"\b(?-i:NF)\b", "nanofiltration"),
        (r"\bsurface\b", "surface water discharge"),
    ],
    "DESAL REASON / TREATMENT": [
        (r"\bTDS\b", "total dissolved solids"),
        (r"\bTOC\b", "total organic carbon"),
        (r"\bH2S\b", "hydrogen sulfide"),
        (r"\bTHMs\b", "trihalomethanes"),
        (r"\bTHM\b", "trihalomethane"),
        (r"\bHAA%?", "haloacetic acids"),
        (r"\bSO4\b", "sulfate"),
        (r"\bNH3\b", "ammonia"),
        (r"\bFe\b", "iron"),
        (r"\bMn\b", "manganese"),
        (r"\bAs\b", "arsenic"),
        (r"\bF\b", "fluoride"),
        (r"\bIX\b", "ion exchange"),
        (r"\bLS\b", "lime softening"),
        (r"\bIPR\b", "indirect potable reuse"),
        (r"\bDW\b", "drinking water"),
    ],
}

CONDUCTIVITY_TO_TDS_FACTOR = 0.64


def read_xml(zip_file: ZipFile, part: str) -> ET.Element:
    return ET.fromstring(zip_file.read(part))


def relationship_part(part: str) -> str:
    base = part.rsplit("/", 1)[-1]
    parent = dirname(part)
    return f"{parent}/_rels/{base}.rels" if parent else f"_rels/{base}.rels"


def resolve_target(source_part: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return normpath(join(dirname(source_part), target))


def column_to_number(column: str) -> int:
    number = 0
    for character in column.upper():
        number = (number * 26) + ord(character) - ord("A") + 1
    return number


def cell_reference_to_position(reference: str) -> tuple[int, int]:
    match = re.fullmatch(r"([A-Za-z]+)([0-9]+)", reference)
    if not match:
        raise ValueError(f"Invalid cell reference: {reference}")
    return int(match.group(2)), column_to_number(match.group(1))


def parse_range(reference: str) -> tuple[int, int, int, int]:
    start, end = reference.split(":") if ":" in reference else (reference, reference)
    start_row, start_col = cell_reference_to_position(start)
    end_row, end_col = cell_reference_to_position(end)
    return start_row, end_row, start_col, end_col


def slugify(value: str, fallback: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or fallback


def load_shared_strings(zip_file: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zip_file.namelist():
        return []

    root = read_xml(zip_file, "xl/sharedStrings.xml")
    strings = []
    for item in root.findall("m:si", NS):
        strings.append("".join(text.text or "" for text in item.findall(".//m:t", NS)))
    return strings


def get_cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.get("t")

    if cell_type == "inlineStr":
        return "".join(text.text or "" for text in cell.findall(".//m:t", NS))

    value = cell.find("m:v", NS)
    if value is None or value.text is None:
        return ""

    raw_value = value.text
    if cell_type == "s":
        try:
            return shared_strings[int(raw_value)]
        except (IndexError, ValueError):
            return raw_value
    if cell_type == "b":
        return "TRUE" if raw_value == "1" else "FALSE"
    return raw_value


def load_workbook_sheets(zip_file: ZipFile, shared_strings: list[str]) -> list[SheetData]:
    workbook = read_xml(zip_file, "xl/workbook.xml")
    workbook_relationships = read_xml(zip_file, "xl/_rels/workbook.xml.rels")
    relationship_targets = {
        relationship.get("Id"): resolve_target("xl/workbook.xml", relationship.get("Target", ""))
        for relationship in workbook_relationships.findall("r:Relationship", NS)
    }

    sheets = []
    for sheet in workbook.findall("m:sheets/m:sheet", NS):
        sheet_name = sheet.get("name", "sheet")
        relationship_id = sheet.get(f"{{{OFFICE_REL_NS}}}id")
        if not relationship_id or relationship_id not in relationship_targets:
            continue

        sheet_part = relationship_targets[relationship_id]
        worksheet = read_xml(zip_file, sheet_part)
        rows: dict[int, dict[int, str]] = {}

        for row in worksheet.findall(".//m:sheetData/m:row", NS):
            row_number = int(row.get("r", "0") or 0)
            if not row_number:
                continue

            values: dict[int, str] = {}
            next_column = 1
            for cell in row.findall("m:c", NS):
                reference = cell.get("r")
                if reference:
                    _, column_number = cell_reference_to_position(reference)
                    next_column = column_number + 1
                else:
                    column_number = next_column
                    next_column += 1

                values[column_number] = get_cell_value(cell, shared_strings)

            if any(value.strip() for value in values.values()):
                rows[row_number] = values

        sheets.append(SheetData(sheet_name, sheet_part, rows))

    return sheets


def get_formal_table_ranges(zip_file: ZipFile, sheet: SheetData) -> list[TableRange]:
    relationship_path = relationship_part(sheet.part)
    if relationship_path not in zip_file.namelist():
        return []

    relationships = read_xml(zip_file, relationship_path)
    ranges = []
    for relationship in relationships.findall("r:Relationship", NS):
        relationship_type = relationship.get("Type", "")
        if not relationship_type.endswith("/table"):
            continue

        table_part = resolve_target(sheet.part, relationship.get("Target", ""))
        table_xml = read_xml(zip_file, table_part)
        reference = table_xml.get("ref")
        if not reference:
            continue

        start_row, end_row, start_col, end_col = parse_range(reference)
        ranges.append(
            TableRange(
                sheet_name=sheet.name,
                name=table_xml.get("displayName") or table_xml.get("name") or "table",
                start_row=start_row,
                end_row=end_row,
                start_col=start_col,
                end_col=end_col,
            )
        )
    return ranges


def row_text(row: dict[int, str]) -> str:
    return " ".join(value.strip() for _, value in sorted(row.items()) if value.strip())


def row_looks_like_table_title(row: dict[int, str]) -> bool:
    nonempty = [value.strip() for value in row.values() if value.strip()]
    if len(nonempty) > 3:
        return False

    text = " ".join(nonempty).upper()
    if "MASTER SPREADSHEET" in text:
        return False
    return "FACILI" in text or "TABLE" in text


def detect_section_tables(sheet: SheetData) -> list[TableRange]:
    row_numbers = sorted(sheet.rows)
    if not row_numbers:
        return []

    basic_rows = [
        row_number
        for row_number in row_numbers
        if "BASIC INFORMATION" in row_text(sheet.rows[row_number]).upper()
    ]
    if not basic_rows:
        return split_on_blank_rows(sheet)

    starts = []
    for row_number in basic_rows:
        start_row = row_number
        earlier_rows = [previous for previous in row_numbers if previous < row_number]
        if earlier_rows:
            previous_row_number = earlier_rows[-1]
            if row_number - previous_row_number <= 3 and row_looks_like_table_title(sheet.rows[previous_row_number]):
                start_row = previous_row_number
        starts.append(start_row)

    ranges = []
    for index, start_row in enumerate(starts):
        next_start = starts[index + 1] if index + 1 < len(starts) else row_numbers[-1] + 1
        included_rows = [row for row in row_numbers if start_row <= row < next_start]
        if not included_rows:
            continue

        end_row = included_rows[-1]
        columns = [
            column
            for row in included_rows
            for column, value in sheet.rows[row].items()
            if value.strip()
        ]
        if not columns:
            continue

        first_text = row_text(sheet.rows[included_rows[0]])
        name = first_text if row_looks_like_table_title(sheet.rows[included_rows[0]]) else f"{sheet.name}_table_{index + 1:02d}"
        ranges.append(
            TableRange(
                sheet_name=sheet.name,
                name=name,
                start_row=start_row,
                end_row=end_row,
                start_col=min(columns),
                end_col=max(columns),
            )
        )
    return ranges


def split_on_blank_rows(sheet: SheetData) -> list[TableRange]:
    row_numbers = sorted(sheet.rows)
    ranges = []
    current: list[int] = []

    for row_number in row_numbers:
        if current and row_number > current[-1] + 1:
            ranges.append(range_from_rows(sheet, current, len(ranges) + 1))
            current = []
        current.append(row_number)

    if current:
        ranges.append(range_from_rows(sheet, current, len(ranges) + 1))
    return [table_range for table_range in ranges if table_range is not None]


def range_from_rows(sheet: SheetData, rows: list[int], index: int) -> TableRange | None:
    columns = [
        column
        for row in rows
        for column, value in sheet.rows[row].items()
        if value.strip()
    ]
    if not columns:
        return None

    return TableRange(
        sheet_name=sheet.name,
        name=f"{sheet.name}_table_{index:02d}",
        start_row=rows[0],
        end_row=rows[-1],
        start_col=min(columns),
        end_col=max(columns),
    )


def table_to_rows(sheet: SheetData, table_range: TableRange) -> list[list[str]]:
    output = []
    for row_number in range(table_range.start_row, table_range.end_row + 1):
        source_row = sheet.rows.get(row_number, {})
        row = [
            source_row.get(column_number, "")
            for column_number in range(table_range.start_col, table_range.end_col + 1)
        ]
        if any(value.strip() for value in row):
            output.append(row)
    return output


def default_state_for_table(table_range: TableRange) -> str:
    name = table_range.name.upper()
    for keyword, state in STATE_BY_SECTION_KEYWORD.items():
        if keyword in name:
            return state
    return ""


def looks_like_state_code(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{2}", value.strip()))


def expand_output_value(column_name: str, value: str) -> str:
    value = value.strip()
    column_expansions = VALUE_EXPANSIONS.get(column_name, {})
    if value in column_expansions:
        return column_expansions[value]

    expanded = value
    for pattern, replacement in TEXT_REPLACEMENTS.get(column_name, []):
        expanded = re.sub(pattern, replacement, expanded, flags=re.IGNORECASE)
    return expanded


def clean_output_text(value: str) -> str:
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s+([,;)])", r"\1", value)
    value = re.sub(r"(\()\s+", r"\1", value)
    value = re.sub(r";\s*", "; ", value)
    return value.strip()


def format_number(value: float) -> str:
    rounded = round(value, 2)
    if rounded.is_integer():
        return str(int(rounded))
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


def convert_numeric_token(match: re.Match[str], multiplier: float) -> str:
    token = match.group(0)
    prefix = "~" if token.startswith("~") else ""
    number = float(token.lstrip("~").replace(",", ""))
    return f"{prefix}{format_number(number * multiplier)}"


def standardize_raw_water_value(value: str) -> str:
    value = value.strip()
    if not value or value.lower() in {"none", "no"}:
        return ""

    normalized = value.replace("µ", "u").replace("μ", "u")
    has_conductivity_unit = bool(re.search(r"uS\s*/\s*cm", normalized, flags=re.IGNORECASE))
    has_tds_unit = bool(re.search(r"m?g\s*/\s*l", normalized, flags=re.IGNORECASE))
    has_numeric_value = bool(re.search(r"~?\d", normalized))
    if not has_numeric_value:
        return ""

    multiplier = CONDUCTIVITY_TO_TDS_FACTOR if has_conductivity_unit else 1.0
    converted = re.sub(r"~?\d[\d,]*(?:\.\d+)?", lambda match: convert_numeric_token(match, multiplier), normalized)
    converted = re.sub(r"uS\s*/\s*cm", "", converted, flags=re.IGNORECASE)
    converted = re.sub(r"m?g\s*/\s*l", "", converted, flags=re.IGNORECASE)
    converted = re.sub(r"\s+", " ", converted)
    converted = re.sub(r"\s+([,;)])", r"\1", converted)
    converted = re.sub(r"(\()\s+", r"\1", converted)
    converted = re.sub(r";\s*", "; ", converted)
    converted = converted.replace(" ,", ",").strip(" ;,")
    if not converted:
        return ""

    if has_conductivity_unit:
        return f"{converted} mg/L TDS equivalent"
    if has_tds_unit or has_numeric_value:
        return f"{converted} mg/L TDS equivalent"
    return converted


def output_value(column_name: str, value: str) -> str:
    if column_name == "RAW WATER TDS OR CONDUCTIVITY":
        value = standardize_raw_water_value(value)
        return value if value else "none"

    value = expand_output_value(column_name, value)
    value = clean_output_text(value)
    return value if value else "none"


def find_data_start_row(sheet: SheetData, table_range: TableRange) -> int:
    header_rows = []
    for row_number in range(table_range.start_row, table_range.end_row + 1):
        row = sheet.rows.get(row_number, {})
        text = row_text(row).upper()
        if row.get(2, "").strip().upper() == "COUNTY":
            header_rows.append(row_number)
        elif any(token in text for token in ("BASIC INFORMATION", "ADDITIONAL INFORMATION")):
            header_rows.append(row_number)
        elif row_number == table_range.start_row and row_looks_like_table_title(row):
            header_rows.append(row_number)

    return (max(header_rows) + 1) if header_rows else table_range.start_row


def normalized_table_rows(sheet: SheetData, table_range: TableRange) -> list[list[str]]:
    rows = []
    data_start_row = find_data_start_row(sheet, table_range)
    default_state = default_state_for_table(table_range)

    for row_number in range(data_start_row, table_range.end_row + 1):
        source_row = sheet.rows.get(row_number, {})
        if not any(value.strip() for value in source_row.values()):
            continue

        source_name = source_row.get(3, "").strip()
        record = []
        for column_name in STANDARD_COLUMNS:
            if column_name == "SOURCE SECTION":
                record.append(table_range.name)
            elif column_name == "SOURCE EXCEL ROW":
                record.append(str(row_number))
            else:
                source_column = SOURCE_COLUMN_BY_OUTPUT_COLUMN[column_name]
                value = source_row.get(source_column, "").strip()
                if column_name == "STATE" and not looks_like_state_code(value):
                    value = default_state
                record.append(output_value(column_name, value))

        if source_name:
            rows.append(record)

    return rows


def write_csv(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerows(rows)


def convert_workbook(workbook_path: Path) -> list[Path]:
    output_paths: list[Path] = []

    with ZipFile(workbook_path) as zip_file:
        shared_strings = load_shared_strings(zip_file)
        sheets = load_workbook_sheets(zip_file, shared_strings)
        sheets_by_name = {sheet.name: sheet for sheet in sheets}

        detected_tables: list[TableRange] = []
        for sheet in sheets:
            formal_tables = get_formal_table_ranges(zip_file, sheet)
            detected_tables.extend(formal_tables or detect_section_tables(sheet))

        combined_rows: list[list[str]] = [STANDARD_COLUMNS]
        for index, table_range in enumerate(detected_tables, start=1):
            sheet = sheets_by_name[table_range.sheet_name]
            rows = normalized_table_rows(sheet, table_range)
            if not rows:
                continue

            table_slug = slugify(table_range.name, f"table_{index:02d}")
            sheet_slug = slugify(table_range.sheet_name, "sheet")
            output_path = workbook_path.with_name(
                f"{workbook_path.stem}_{sheet_slug}_{index:02d}_{table_slug}.csv"
            )
            write_csv(output_path, [STANDARD_COLUMNS, *rows])
            output_paths.append(output_path)

            combined_rows.extend(rows)

        if len(combined_rows) > 1:
            combined_path = workbook_path.with_name(f"{workbook_path.stem}_all_tables.csv")
            write_csv(combined_path, combined_rows)
            output_paths.append(combined_path)

    return output_paths


def find_default_workbook(script_dir: Path) -> Path:
    workbooks = sorted(
        path for path in script_dir.glob("*.xlsx") if not path.name.startswith("~$")
    )
    if not workbooks:
        raise FileNotFoundError(f"No .xlsx file found in {script_dir}")
    if len(workbooks) > 1:
        names = ", ".join(path.name for path in workbooks)
        raise ValueError(f"Found multiple .xlsx files; choose one explicitly: {names}")
    return workbooks[0]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert all table-like ranges in an XLSX workbook to CSV files."
    )
    parser.add_argument(
        "workbook",
        nargs="?",
        type=Path,
        help="Path to the .xlsx workbook. Defaults to the only .xlsx file beside this script.",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    workbook_path = args.workbook or find_default_workbook(script_dir)
    if not workbook_path.is_absolute():
        workbook_path = (Path.cwd() / workbook_path).resolve()

    output_paths = convert_workbook(workbook_path)
    if not output_paths:
        print(f"No table-like ranges found in {workbook_path}", file=sys.stderr)
        return 1

    print(f"Created {len(output_paths)} CSV file(s):")
    for path in output_paths:
        print(f" - {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

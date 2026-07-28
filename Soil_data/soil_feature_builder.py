#!/usr/bin/env python3
"""Shared builder that turns SSURGO tabular tables into expert-selected features.

Given the tabular tables for a survey (as {physical_stem: list[dict]}) and the
expert's Selected_columns_dictionary.csv, `SoilFeatureBuilder` produces feature
rows at (component x horizon) granularity for any map unit. Both the per-polygon
survey extractor and the per-mukey soil-dimension builder use it, so the join
logic lives in one place.

Because every SSURGO survey shares an identical table/column schema, the output
column set is fixed from the dictionary (not from which columns a given survey
happens to populate), so a combined table across surveys stays aligned.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path


csv.field_size_limit(10_000_000)

# Logical table name (dictionary) -> physical CSV/txt stem.
LOGICAL_TO_STEM = {
    "component": "comp",
    "chorizon": "chorizon",
    "chfrags": "chfrags",
    "chpores": "chpores",
    "chstructgrp": "chstrgrp",
    "chtexture": "chtextur",
    "comonth": "cmonth",
    "cocanopycover": "ccancov",
}

# Horizon sub-tables prefixed on output to avoid column-name collisions.
HORIZON_SUBTABLES = ["chfrags", "chpores", "chstructgrp", "chtexture"]

# Soil-type identity kept on every row in addition to the expert selection, so
# soils can be grouped/joined by series and taxonomy later.
COMPONENT_IDENTITY = ["cokey", "compname", "compkind", "component_percent", "majcompflag"]
EXTRA_TAXONOMY = ["taxgrtgroup", "taxsubgrp", "taxclname"]

# Physical stems the builder needs (chtexgrp is the chkey->chtgkey bridge).
REQUIRED_STEMS = [
    "mapunit", "comp", "chorizon", "chfrags", "chpores",
    "chstrgrp", "chtextur", "chtexgrp", "cmonth", "ccancov",
]

FLOOD_SEVERITY = {
    "none": 0, "very rare": 1, "rare": 2, "occasional": 3,
    "frequent": 4, "very frequent": 5,
}


def to_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("-inf")


def read_selected_columns(dictionary_path: Path) -> dict[str, list[str]]:
    selected: dict[str, list[str]] = defaultdict(list)
    with dictionary_path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            selected[row["table"]].append(row["column_name"])
    return selected


def index_by(rows: list[dict[str, str]], key: str) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row.get(key, "")].append(row)
    return grouped


def pick_rvindicator(rows: list[dict[str, str]]) -> dict[str, str] | None:
    if not rows:
        return None
    for row in rows:
        if row.get("rvindicator", "").strip().lower() == "yes":
            return row
    return rows[0]


class SoilFeatureBuilder:
    def __init__(self, tables: dict[str, list[dict[str, str]]], selected: dict[str, list[str]]):
        self.component_columns = list(selected.get("component", []))
        self.chorizon_columns = list(selected.get("chorizon", []))
        self.subtable_columns = {logical: list(selected.get(logical, [])) for logical in HORIZON_SUBTABLES}

        self.components_by_mukey = index_by(tables.get("comp", []), "mukey")
        self.horizons_by_cokey = index_by(tables.get("chorizon", []), "cokey")
        self.mapunit_by_mukey = {row.get("mukey", ""): row for row in tables.get("mapunit", [])}

        self.horizon_lookups = self._build_horizon_lookups(tables)
        self.flooding, self.canopy = self._build_component_sublookups(tables)

    def _build_horizon_lookups(self, tables):
        lookups: dict[str, dict[str, dict[str, str]]] = {}
        for logical in ("chpores", "chstructgrp"):
            by_chkey = index_by(tables.get(LOGICAL_TO_STEM[logical], []), "chkey")
            lookups[logical] = {chkey: pick_rvindicator(rows) for chkey, rows in by_chkey.items()}

        frags_by_chkey = index_by(tables.get("chfrags", []), "chkey")
        lookups["chfrags"] = {
            chkey: max(rows, key=lambda r: to_float(r.get("fragvol_r", "")))
            for chkey, rows in frags_by_chkey.items()
        }

        chtexgrp_by_chkey = index_by(tables.get("chtexgrp", []), "chkey")
        texture_by_chtgkey = index_by(tables.get("chtextur", []), "chtgkey")

        def representative_texture(rows):
            for row in rows:
                if row.get("texcl", "").strip():
                    return row
            return rows[0]

        texture_rep: dict[str, dict[str, str]] = {}
        for chkey, groups in chtexgrp_by_chkey.items():
            rv_group = pick_rvindicator(groups)
            if rv_group is None:
                continue
            texture_rows = texture_by_chtgkey.get(rv_group.get("chtgkey", ""), [])
            if texture_rows:
                texture_rep[chkey] = representative_texture(texture_rows)
        lookups["chtexture"] = texture_rep
        return lookups

    def _build_component_sublookups(self, tables):
        flooding: dict[str, tuple[int, str]] = {}
        for row in tables.get("cmonth", []):
            cokey = row.get("cokey", "")
            label = row.get("flodfreqcl", "").strip()
            if not label:
                continue
            severity = FLOOD_SEVERITY.get(label.lower(), 0)
            if cokey not in flooding or severity > flooding[cokey][0]:
                flooding[cokey] = (severity, label)

        canopy: dict[str, tuple[float, str]] = {}
        for row in tables.get("ccancov", []):
            cokey = row.get("cokey", "")
            cover = to_float(row.get("plantcov", ""))
            if cover == float("-inf"):
                continue
            if cokey not in canopy or cover > canopy[cokey][0]:
                canopy[cokey] = (cover, row.get("plantcov", ""))

        return (
            {cokey: label for cokey, (_, label) in flooding.items()},
            {cokey: label for cokey, (_, label) in canopy.items()},
        )

    def feature_columns(self) -> list[str]:
        columns = [
            *COMPONENT_IDENTITY,
            *self.component_columns,
            *EXTRA_TAXONOMY,
            "flodfreqcl",
            "plantcov",
            "chkey",
            *self.chorizon_columns,
        ]
        for logical in HORIZON_SUBTABLES:
            columns.extend(f"{logical}_{column}" for column in self.subtable_columns[logical])
        return columns

    def muname(self, mukey: str) -> str:
        return self.mapunit_by_mukey.get(mukey, {}).get("muname", "")

    def rows_for_mukey(self, mukey: str) -> list[dict[str, str]]:
        components = sorted(
            self.components_by_mukey.get(mukey, []),
            key=lambda c: to_float(c.get("comppct_r", "")),
            reverse=True,
        )
        rows: list[dict[str, str]] = []
        for component in components:
            cokey = component.get("cokey", "")
            base = {
                "cokey": cokey,
                "compname": component.get("compname", ""),
                "compkind": component.get("compkind", ""),
                "component_percent": component.get("comppct_r", ""),
                "majcompflag": component.get("majcompflag", ""),
                **{column: component.get(column, "") for column in self.component_columns},
                **{column: component.get(column, "") for column in EXTRA_TAXONOMY},
                "flodfreqcl": self.flooding.get(cokey, ""),
                "plantcov": self.canopy.get(cokey, ""),
            }
            horizons = sorted(
                self.horizons_by_cokey.get(cokey, []),
                key=lambda h: to_float(h.get("hzdept_r", "")),
            )
            if not horizons:
                rows.append({**base, "chkey": ""})
                continue
            for horizon in horizons:
                chkey = horizon.get("chkey", "")
                row = {
                    **base,
                    "chkey": chkey,
                    **{column: horizon.get(column, "") for column in self.chorizon_columns},
                }
                for logical in HORIZON_SUBTABLES:
                    sub_row = self.horizon_lookups[logical].get(chkey)
                    for column in self.subtable_columns[logical]:
                        row[f"{logical}_{column}"] = sub_row.get(column, "") if sub_row else ""
                rows.append(row)
        return rows

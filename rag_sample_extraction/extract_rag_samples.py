#!/usr/bin/env python3
"""RAG sample extraction: hard-filter, then similarity, then top-k positive samples.

For a query plant, this selects the most similar existing plants from the public
dataset to use as positive few-shot examples in a prompt. Selection has two stages:

  1. HARD FILTERS (applied first, must all pass) — a candidate is only comparable
     if it shares the query's:
       - intended purpose        (PURPOSE)       — different purposes are regulated differently
       - source water            (WATER SOURCE)  — drives salinity / sodium / ion makeup
       - process family          (TYPE)          — e.g. RO behaves differently from NF
  2. SIMILARITY (on the survivors) — weighted distance over the water-quality analyte
     features (median values), log-scaled and standardized. Weights are EQUAL for
     now; the design accepts a per-analyte weight file so an expert's feature-
     importance ranking can be plugged in later without code changes.

The top-k most similar survivors are returned as the positive samples.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = REPO_ROOT / "Water_quality_data" / "outputs" / "water_quality_stats_30yr_per_plant.csv"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"

ID_COLUMN = "SOURCE EXCEL ROW"

# Hard-filter fields and how each categorical value is normalized for equality.
FILTER_FIELDS = ["purpose", "source", "process"]
FILTER_SOURCE_COLUMN = {"purpose": "PURPOSE", "source": "WATER SOURCE", "process": "TYPE"}

# Analyte similarity features: (name, median column, log-transform?).
# Concentrations/conductances span orders of magnitude, so they are log-scaled;
# pH is already logarithmic and temperature is linear, so both stay untransformed.
ANALYTE_FEATURES = [
    ("tds_mg_l", "tds_mg_l_median", True),
    ("spec_conductance_us_cm", "spec_conductance_us_cm_median", True),
    ("salinity_ppth", "salinity_ppth_median", True),
    ("conductivity_us_cm", "conductivity_us_cm_median", True),
    ("calcium_mg_l", "calcium_mg_l_median", True),
    ("magnesium_mg_l", "magnesium_mg_l_median", True),
    ("sodium_mg_l", "sodium_mg_l_median", True),
    ("potassium_mg_l", "potassium_mg_l_median", True),
    ("ph", "ph_median", False),
    ("temperature_deg_c", "temperature_deg_c_median", False),
    ("turbidity_ntu", "turbidity_ntu_median", True),
]

SUMMARY_COLUMNS = [ID_COLUMN, "NAME", "STATE", "COUNTY", "TYPE", "WATER SOURCE", "PURPOSE"]


@dataclass
class Plant:
    plant_id: str
    row: dict[str, str]
    filters: dict[str, str]           # normalized categorical values ("" = unknown)
    features: dict[str, float | None]  # analyte name -> median value (or None if missing)


# --- normalization -----------------------------------------------------------

def _clean(value: str) -> str:
    value = (value or "").strip().lower()
    return "" if value in ("", "none", "n/a", "na", "null") else value


def normalize_purpose(value: str) -> str:
    return _clean(value)


def normalize_source(value: str) -> str:
    return _clean(value)


def normalize_process(value: str) -> str:
    """Map a process type to a coarse family so RO variants group together."""
    text = _clean(value)
    if not text:
        return ""
    if "reverse osmosis" in text:
        return "ro"
    if "nanofiltration" in text:
        return "nf"
    if "electrodialysis" in text:
        return "ed"
    if "ultrafiltration" in text or "microfiltration" in text:
        return "membrane_filtration"
    return "other"


NORMALIZERS = {"purpose": normalize_purpose, "source": normalize_source, "process": normalize_process}


def parse_number(value: str) -> float | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


# --- loading -----------------------------------------------------------------

def load_plants(dataset_path: Path) -> list[Plant]:
    with dataset_path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    plants: list[Plant] = []
    for row in rows:
        filters = {name: NORMALIZERS[name](row.get(FILTER_SOURCE_COLUMN[name], "")) for name in FILTER_FIELDS}
        features = {name: parse_number(row.get(column, "")) for name, column, _ in ANALYTE_FEATURES}
        plants.append(Plant(plant_id=row.get(ID_COLUMN, ""), row=row, filters=filters, features=features))
    return plants


def load_weights(path: Path | None) -> dict[str, float]:
    weights = {name: 1.0 for name, _, _ in ANALYTE_FEATURES}  # equal by default
    if path is None:
        return weights
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        provided = {str(k): float(v) for k, v in data.items()}
    else:  # two-column CSV: analyte,weight
        provided = {}
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for record in csv.DictReader(handle):
                fields = list(record.values())
                if len(fields) >= 2 and fields[1].strip():
                    provided[str(fields[0]).strip()] = float(fields[1])
    for name in weights:
        if name in provided:
            weights[name] = provided[name]
    return weights


# --- scaling + similarity ----------------------------------------------------

def transform(value: float, log: bool) -> float:
    return math.log1p(value) if log else value


def build_scaler(plants: list[Plant]) -> dict[str, tuple[float, float]]:
    """Per-analyte (mean, std) of transformed values across the dataset."""
    scaler: dict[str, tuple[float, float]] = {}
    for name, _, log in ANALYTE_FEATURES:
        vals = [transform(p.features[name], log) for p in plants if p.features[name] is not None]
        if len(vals) < 2:
            continue
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)
        std = math.sqrt(var)
        if std > 1e-12:
            scaler[name] = (mean, std)
    return scaler


def standardized(plant: Plant, scaler: dict[str, tuple[float, float]]) -> dict[str, float]:
    z: dict[str, float] = {}
    for name, _, log in ANALYTE_FEATURES:
        value = plant.features[name]
        if value is None or name not in scaler:
            continue
        mean, std = scaler[name]
        z[name] = (transform(value, log) - mean) / std
    return z


def similarity(query_z: dict[str, float], cand_z: dict[str, float], weights: dict[str, float]) -> tuple[float, int]:
    """Gower-style weighted distance -> similarity in (0, 1]; also returns dims used."""
    weighted_sq = 0.0
    weight_sum = 0.0
    used = 0
    for name, zq in query_z.items():
        if name not in cand_z:
            continue
        w = weights.get(name, 1.0)
        weighted_sq += w * (zq - cand_z[name]) ** 2
        weight_sum += w
        used += 1
    if weight_sum == 0:
        return 0.0, 0
    distance = math.sqrt(weighted_sq / weight_sum)
    return 1.0 / (1.0 + distance), used


# --- extraction --------------------------------------------------------------

def passes_hard_filters(query: Plant, candidate: Plant, active: list[str]) -> bool:
    for name in active:
        q = query.filters[name]
        if not q:
            continue  # query value unknown -> cannot filter on it
        if candidate.filters[name] != q:
            return False
    return True


@dataclass
class Match:
    candidate: Plant
    score: float
    features_used: int


def extract_samples(
    query: Plant,
    plants: list[Plant],
    scaler: dict[str, tuple[float, float]],
    weights: dict[str, float],
    active_filters: list[str],
    top_k: int,
    bottom_k: int,
    exclude_same_county: bool,
) -> tuple[list[Match], list[Match]]:
    """Return (top_k most similar, bottom_k least similar) from the filtered pool.

    The same hard filters gate both. The two selections never overlap: the bottom
    is taken from candidates not already in the top.
    """
    query_z = standardized(query, scaler)
    query_county = (query.row.get("STATE", ""), query.row.get("COUNTY", ""))
    matches: list[Match] = []
    for candidate in plants:
        if candidate.plant_id == query.plant_id:
            continue
        if exclude_same_county and (candidate.row.get("STATE", ""), candidate.row.get("COUNTY", "")) == query_county:
            continue
        if not passes_hard_filters(query, candidate, active_filters):
            continue
        score, used = similarity(query_z, standardized(candidate, scaler), weights)
        if used == 0:
            continue
        matches.append(Match(candidate=candidate, score=score, features_used=used))
    matches.sort(key=lambda m: m.score, reverse=True)

    top = matches[:top_k]
    bottom: list[Match] = []
    if bottom_k > 0:
        remaining = matches[len(top):]  # exclude everything already chosen for the top
        bottom = list(reversed(remaining[-bottom_k:]))  # least similar first
    return top, bottom


def match_rows(query: Plant, matches: list[Match], selection: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for rank, match in enumerate(matches, start=1):
        record = {"query_row": query.plant_id, "selection": selection, "rank": str(rank),
                  "similarity": f"{match.score:.4f}", "features_used": str(match.features_used)}
        for column in SUMMARY_COLUMNS:
            record[column] = match.candidate.row.get(column, "")
        for name, column, _ in ANALYTE_FEATURES:
            record[column] = match.candidate.row.get(column, "")
        out.append(record)
    return out


def output_fieldnames() -> list[str]:
    return (["query_row", "selection", "rank", "similarity", "features_used", *SUMMARY_COLUMNS]
            + [column for _, column, _ in ANALYTE_FEATURES])


def find_plant(plants: list[Plant], plant_id: str) -> Plant:
    for plant in plants:
        if plant.plant_id == plant_id:
            return plant
    raise SystemExit(f"query row {plant_id!r} not found in dataset")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="Per-plant stats CSV")
    parser.add_argument("--query-row", help=f"{ID_COLUMN} of the query plant (leave-one-out). Omit with --all-queries.")
    parser.add_argument("--all-queries", action="store_true", help="Run every plant as a query (leave-one-out) and write a combined table")
    parser.add_argument("--top-k", type=int, default=5, help="Number of most-similar samples to return (default 5)")
    parser.add_argument("--bottom-k", type=int, default=0, help="Number of least-similar (dissimilar) samples to also return, from the same filtered pool (default 0)")
    parser.add_argument(
        "--filters",
        default=",".join(FILTER_FIELDS),
        help=f"Comma-separated hard filters to apply from {FILTER_FIELDS} (default all). Use 'none' to disable.",
    )
    parser.add_argument("--weights", type=Path, default=None, help="Optional analyte->weight file (json or 2-col csv); default equal weights")
    parser.add_argument("--exclude-same-county", action="store_true", help="Drop candidates in the query's own state+county (avoid shared-neighborhood leakage)")
    parser.add_argument("--output", type=Path, default=None, help="Output CSV path (default under outputs/)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.query_row and not args.all_queries:
        raise SystemExit("provide --query-row <id> or --all-queries")

    plants = load_plants(args.dataset)
    scaler = build_scaler(plants)
    weights = load_weights(args.weights)
    active = [] if args.filters.strip().lower() == "none" else [f.strip() for f in args.filters.split(",") if f.strip() in FILTER_FIELDS]

    print(f"Loaded {len(plants)} plants; similarity over {len(scaler)} usable analytes; hard filters: {active or 'none'}", flush=True)
    print(f"Weights: {'equal' if args.weights is None else args.weights.name}", flush=True)

    queries = plants if args.all_queries else [find_plant(plants, args.query_row)]
    all_records: list[dict[str, str]] = []
    for query in queries:
        if not standardized(query, scaler):
            if not args.all_queries:
                print(f"query row {query.plant_id} has no usable analyte data; nothing to compare", flush=True)
            continue
        top, bottom = extract_samples(query, plants, scaler, weights, active, args.top_k, args.bottom_k, args.exclude_same_county)
        records = match_rows(query, top, "top") + match_rows(query, bottom, "bottom")
        all_records.extend(records)
        if not args.all_queries:
            print(f"\nQuery: row {query.plant_id} — {query.row.get('NAME','')} "
                  f"({query.row.get('STATE','')}/{query.row.get('COUNTY','')}, {query.row.get('TYPE','')}, "
                  f"{query.row.get('WATER SOURCE','')}, {query.row.get('PURPOSE','')})", flush=True)

            def show(label: str, group: list[dict[str, str]]) -> None:
                for record in group:
                    print(f"  [{label}] #{record['rank']} sim={record['similarity']} (feats={record['features_used']})  "
                          f"row {record[ID_COLUMN]}  {record['NAME'][:34]:34} {record['STATE']}/{record['COUNTY'][:10]:10} "
                          f"{record['TYPE'][:20]:20} TDS_med={record.get('tds_mg_l_median','')}", flush=True)

            print(f"Most similar (top {args.top_k}) of {len(top)} shown:", flush=True)
            show("top", match_rows(query, top, "top"))
            if args.bottom_k > 0:
                print(f"Least similar (bottom {args.bottom_k}) of {len(bottom)} shown:", flush=True)
                show("bottom", match_rows(query, bottom, "bottom"))

    if args.output:
        output_path = args.output
    elif args.all_queries:
        output_path = DEFAULT_OUTPUT_DIR / "rag_topk_all_queries.csv"
    else:
        output_path = DEFAULT_OUTPUT_DIR / f"rag_topk_query_{args.query_row}.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_fieldnames(), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_records)
    print(f"\nWrote {len(all_records)} match rows to {output_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

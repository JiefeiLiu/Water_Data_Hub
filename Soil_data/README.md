# Soil Data (SSURGO) Processing

Downloads USDA NRCS **SSURGO** soil survey data, matches each public-dataset facility to
the soil map unit it sits on, and builds a per-`mukey` soil-feature table that links back
to the public data by a single key.

**End products:**

- `public_data/processed_data/report207appendixA_all_tables_labeled_acc_soil_location_matches.csv` — each facility → its soil map unit (`soil_match_mukey`, `soil_match_polygon_acres`).
- `outputs/soil_features_dimension.csv` — the soil profile (selected features) per map unit; join on `soil_match_mukey`.

---

## Pipeline Overview

| # | Step | Script | Reads | Writes |
|---|------|--------|-------|--------|
| 1 | **Download** SSURGO zips by state/county | `download_public_data_ssurgo.py` | `public_data/metadata/report207appendixA_all_tables.csv` | `public_data_ssurgo_zips/`, `metadata/public_data_ssurgo_manifest.csv` |
| 2 | **Match** each facility to its soil polygon | `match_public_data_soil_locations.py` | `public_data/metadata/..._labeled_acc.csv` + `public_data_ssurgo_zips/` | `public_data/processed_data/..._soil_location_matches.csv` |
| 3 | **Build** the per-`mukey` soil-feature table | `build_soil_dimension.py` | `metadata/Selected_columns_dictionary.csv` + matched zips | `outputs/soil_features_dimension.csv` |

Link the results: `soil_location_matches.soil_match_mukey → soil_features_dimension.mukey`.

### Reproduce

Run from the repo root. Step 1 is slow (network, ~28 GB) but incremental — it skips
counties already downloaded.

```bash
# 1. Download SSURGO survey zips for the public dataset's state/counties
python Soil_data/download_public_data_ssurgo.py --skip-recorded-searches

# 2. Match each facility coordinate to the SSURGO map-unit polygon it falls in
python Soil_data/match_public_data_soil_locations.py

# 3. Build the per-mukey soil-feature table the matches link into
python Soil_data/build_soil_dimension.py
```

---

## Key Concepts (how SSURGO is organized)

A facility coordinate resolves to soil data through this hierarchy:

```
facility coordinate
  └─ point-in-polygon → soil map-unit POLYGON      ← the mapped LOCATION (one delineation)
        └─ its mukey → MAP UNIT                     ← a soil TYPE / class (the polygon's label)
              └─ COMPONENTS (as % area)             ← the soil types in that map unit
                    └─ HORIZONS (depth layers)      ← where the property values live
```

- A **map unit** (`mukey`) is a soil *type*, not a place. The same map unit is drawn as many
  **polygons** (locations) across a survey area. `mukey` is nationally unique.
- A map unit bundles several **components** (soil types) as **area percentages with no internal
  geography** — so at a point we know the map unit exactly, but not which component underfoot.
- Each component has multiple **horizons** (depth layers), each with its own chemistry.

Consequence: one facility → one polygon → **many soil rows** (every component × horizon).

---

## Step 1 — Download

Reads state/county from `public_data/metadata/report207appendixA_all_tables.csv`, searches
Web Soil Survey for each, and keeps every SSURGO survey-area zip returned. One source county
can map to several survey-area packages.

- Source states: 16 · matched manifest rows: 1,299 · unique SSURGO zip packages: **1,268** (~28 GB on disk)
- `metadata/public_data_ssurgo_downloaded_counties.json` records completed searches so
  `--skip-recorded-searches` resumes without re-downloading.
- One search did not match a WSS county: `CA, SANTA MONICA`.

Every survey shares an identical 68-table tabular schema, so extraction logic is uniform
across all 1,268 packages.

```bash
python Soil_data/download_public_data_ssurgo.py --skip-recorded-searches   # incremental download
python Soil_data/download_public_data_ssurgo.py --registry-from-manifest   # rebuild the registry offline
```

---

## Step 2 — Match To Public Data

`match_public_data_soil_locations.py` links each facility to the soil beneath it.

- **Input coordinates:** `ACC_X` = latitude, `ACC_Y` = longitude (same columns as the water pipeline).
- **Candidate surveys:** chosen by the facility's state/county via `metadata/public_data_ssurgo_manifest.csv`.
- **Primary match — point in polygon:** finds the SSURGO map-unit polygon that *contains* the
  coordinate and takes that polygon's `mukey`. Because SSURGO polygons tile the landscape with
  no gaps, this is authoritative (distance 0), not a nearest-neighbor guess.
- **Fallback — nearest centroid:** if no polygon contains the point (e.g. a coordinate just off
  the surveyed area), it takes the nearest map-unit-polygon centroid within `--max-nearest-km`
  (default 10 km); beyond that the row is left unmatched.
- **Confidence column:** `soil_match_polygon_acres` — the area of the matched delineation.
  SSURGO polygons range from < 3 to > 90,000 acres, so a small polygon is a far more local match
  than a huge one.

Output columns (appended to the public data):

```text
soil_match_status, soil_match_method, soil_match_distance_km, soil_match_area_symbol,
soil_match_folder, soil_match_zip, soil_match_mukey, soil_match_musym,
soil_match_longitude, soil_match_latitude, soil_match_polygon_acres, soil_match_note
```

Current results (86 public rows):

- **Matched: 75** — 74 by containing polygon, 1 by nearest centroid
- Unmatched: 8 missing coordinates, 2 nearest polygon > 10 km, 1 with no downloaded survey
- 75 matches span **69 unique map units** across **58 survey areas**; polygon areas 2.7 – 94,085 acres

```bash
python Soil_data/match_public_data_soil_locations.py                 # default 10 km fallback
python Soil_data/match_public_data_soil_locations.py --max-nearest-km 5
```

---

## Step 3 — Build The Soil-Feature Table

`build_soil_dimension.py` produces the reusable soil "library" the matches link into.

- Reads the expert-selected columns from `metadata/Selected_columns_dictionary.csv` and the
  survey zips referenced by the match file (so it covers exactly the map units the plants need).
- Emits **one row per `(mukey × component × horizon)`**, keyed by `mukey` (+ `cokey`, `chkey`),
  combined across surveys. Because `mukey` is nationally unique, rows from different surveys
  never collide.
- **Every component is emitted, not just the dominant one.** Many "Urban land–…" complexes have
  an empty dominant component but a minor component that carries the real chemistry, so keeping
  all of them avoids silently returning blanks.
- **Confidence column:** `component_percent` (`comppct_r`) — the map-unit share of the soil type
  in that row.
- Also carries soil-type identity (`compname`, `compkind`, `taxorder … taxclname`) alongside the
  selected features.

Current table: **63,870 rows**, **5,205 unique map units**, 176 columns.

```bash
python Soil_data/build_soil_dimension.py
```

`extract_soil_selected_features.py` is a related per-survey variant: it writes one row per
`(polygon × component × horizon)` for a single unpacked survey folder, adding `polygon_acres`
and centroid coordinates — handy for exploring one survey with its geometry attached.

---

## Linking Soil Features To A Facility

The design is a **foreign-key link**, so no soil detail is flattened away:

```
soil_location_matches.csv                        soil_features_dimension.csv
  facility row                                     mukey, cokey, chkey,
  soil_match_mukey  ───────────────────────────►   compname, component_percent,
  soil_match_polygon_acres                          horizon depths, pH, SAR, CEC, texture, ...
```

To pull a facility's soil profile, filter the dimension where `mukey == soil_match_mukey`.
Expect **many rows** per facility (all components × horizons of its map unit). Collapse them
however the model needs — e.g. the best data-bearing component's surface horizon, or a
percent-/depth-weighted summary — using `component_percent` and the horizon depths.

The public-data water-quality file also carries `soil_match_mukey` (added by
`public_data/link_soil_key_to_wqp_features.py`), so soil and water results are reachable from
one table.

---

## Selected Features And Column Dictionary

- `metadata/Selected_columns_dictionary.csv` — the expert-chosen feature columns (164 columns
  across `component`, `chorizon`, `chfrags`, `chpores`, `chstructgrp`, `chtexture`, `comonth`,
  `cocanopycover`) that Step 3 extracts.
- Per-survey column dictionary — `extract_ssurgo_column_dictionary.py` flattens each survey's
  `mstabcol.txt`/`msdomdet.txt` into a readable `_columns_dictionary.csv` (label, units, valid
  range, coded values, description) so every feature name is explained.
- Per-survey tabular CSVs — `convert_fl071_tabular_to_csv.py --base-dir <survey>` converts a
  survey's 68 tabular `.txt` tables to clean CSVs plus a `_tables_index.csv` summary.

---

## Legacy Centroid Export

`outputs/public_data_ssurgo_mapunit_centroid_soil_values.csv` is an earlier one-row-per-polygon
summary (dominant component's surface horizon, representative values only), generated by
`extract_public_data_ssurgo.py` across all 1,268 zips (15,096,584 rows, ~2.0 GB). It predates the
selected-feature/`mukey`-linked design and picks the *dominant* component, so it can return
blanks where the dominant component has no horizon data. Prefer the Step 3 dimension for
modeling; this file remains for the broad centroid summary.

Its columns: `areasymbol, spatialver, longitude, latitude, musym, mukey, muname, component_name,
component_percent_r, horizon_name, horizon_top_cm, horizon_bottom_cm, ph1to1h2o_r, ph01mcacl2_r,
cec7_r, ecec_r, sumbases_r, caco3_r, gypsum_r, sar_r, pbray1_r, poxalate_r, ph2osoluble_r, ptotal_r`.

SSURGO column suffixes `_l`/`_r`/`_h` are low/representative/high values; this legacy file keeps
`_r` only. Blank cells mean the attribute was unpopulated in the source SSURGO data.

## Full Database Export

To preserve every SSURGO table while feature selection evolves, the extractors support a
full-database mode (metadata-derived column names, all tabular + spatial DBF tables):

```bash
python Soil_data/extract_fl071_soil_values.py --full-database --replace     # one sample survey -> FL071/outputs/full_database/
python Soil_data/extract_public_data_ssurgo.py --full-database --replace     # all zips -> outputs/public_data_ssurgo_full_database/
```

The all-zip export combines same-named tables across surveys and adds `source_areasymbol`,
`source_path`, and `survey_root` for traceability. It does not convert full shapefile geometry to
CSV; the original shapefiles remain in the survey `spatial/` folders for spatial joins.

---

## Files And Directories

**Scripts (pipeline order)**

- `download_public_data_ssurgo.py` — Step 1: batch downloader for the state/county searches
- `match_public_data_soil_locations.py` — Step 2: point-in-polygon matcher (adds `soil_match_mukey`, `soil_match_polygon_acres`)
- `build_soil_dimension.py` — Step 3: per-`mukey` selected-feature table
- `soil_feature_builder.py` — shared builder used by Steps 3 and the per-survey extractor
- `extract_soil_selected_features.py` — per-survey, per-polygon selected features (with geometry)
- `extract_ssurgo_column_dictionary.py`, `convert_fl071_tabular_to_csv.py` — per-survey CSV + column-dictionary helpers
- `extract_public_data_ssurgo.py` — legacy centroid export / full-database export
- `download_ssurgo.py`, `ssurgo_full_database.py` — single-area downloader and shared zip helpers

**Data**

- `public_data_ssurgo_zips/` — downloaded raw SSURGO zips, grouped by survey-area symbol
- `FL071/`, `CA696/` — unpacked sample survey areas (with `tabular_csv/`, `_columns_dictionary.csv`)

**metadata/**

- `public_data_ssurgo_manifest.csv` — every matched WSS result: source/matched county, area symbol, zip path, status, URL
- `public_data_ssurgo_unmatched.csv` — searches with no WSS county match
- `public_data_ssurgo_downloaded_counties.json` — completed-search registry for `--skip-recorded-searches`
- `Selected_columns_dictionary.csv` — expert-selected feature columns for Step 3

**outputs/**

- `soil_features_dimension.csv` — per-`mukey` selected-feature table (Step 3 product)
- `public_data_ssurgo_mapunit_centroid_soil_values.csv` — legacy centroid export
- `public_data_ssurgo_processing_errors.csv` — legacy export error log

---

## Data Source

USDA NRCS SSURGO via the Web Soil Survey download service:

- https://websoilsurvey.sc.egov.usda.gov/DSD/Download/help
- https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo

# Water Quality Data (WQP) Processing

This directory downloads Water Quality Portal (WQP) sample results for the state/county locations in the public dataset, matches each public row to nearby WQP monitoring stations, and merges aggregated water-quality features back into the public dataset.

**End product:** the public dataset with water-quality feature columns appended.

```text
public_data/report207appendixA_all_tables_labeled_acc_wqp_features.csv
```

---

## Pipeline Overview

The process is four steps. Each step reads the previous step's output, so they must run in order.

| # | Step | Script | Reads | Writes |
|---|------|--------|-------|--------|
| 1 | **Download** WQP results by state/county | `download_public_data_wqp.py` | `public_data/report207appendixA_all_tables.csv` | `wqp_result_zips/`, `public_data_wqp_manifest.csv` |
| 2 | **Match** public coordinates to WQP stations | `match_public_data_wqp_locations.py` | `..._labeled_acc.csv` + `wqp_result_zips/` | `..._wqp_location_matches.csv` |
| 3 | **Merge** aggregated features into the dataset | `add_public_data_wqp_features.py` | `..._wqp_location_matches.csv` | `..._wqp_features.csv` |
| 4 | **Check** missing values | `print_public_data_missingness.py` | `..._wqp_features.csv` | `outputs/public_data_wqp_feature_missingness.csv` |

All paths above are relative to the repo root; `...` is `public_data/report207appendixA_all_tables_labeled_acc`.

### Reproduce everything

Run from the repo root. Step 1 is slow (network) and is safe to skip if `wqp_result_zips/` is already populated.

```bash
# 1. Download WQP result zips (skips counties already downloaded)
python Water_quality_data/download_public_data_wqp.py --skip-recorded-searches

# 2. Match each public row to nearby WQP stations
python Water_quality_data/match_public_data_wqp_locations.py

# 3. Merge water-quality features into the public dataset
python Water_quality_data/add_public_data_wqp_features.py --aggregate-nearby

# 4. Report missing values
python Water_quality_data/print_public_data_missingness.py \
  --output Water_quality_data/outputs/public_data_wqp_feature_missingness.csv
```

---

## Step 1 — Download

Reads `STATE` and `COUNTY` from `public_data/report207appendixA_all_tables.csv`. For each unique state/county it queries the WQP Result service twice, once per characteristic group, and saves a zipped CSV per query into `wqp_result_zips/<state FIPS>/`.

Query settings:

- **Location:** WQP `countycode` (or `statecode` when the row has no county)
- **Sample media:** `water`, `Water`
- **Characteristic groups:** one query for `Inorganics, Major, Metals`, one for `Physical`
- **Providers:** `NWIS`, `STEWARDS`, `STORET`
- **Format:** zipped CSV, `sorted=no` (faster for large downloads)

Desalination-focused characteristic names are requested per group:

- `Inorganics, Major, Metals`: alkalinity, bicarbonate, carbonate, hardness, calcium, magnesium, sodium, potassium, chloride, sulfate, fluoride, boron, silica, iron, manganese, nitrate, nitrite, sodium adsorption ratio, sodium plus potassium
- `Physical`: pH, conductivity, specific conductance, salinity, total dissolved solids, temperature, water temperature, turbidity

```bash
# Full download, skipping counties already in the registry
python Water_quality_data/download_public_data_wqp.py --skip-recorded-searches

# Build the manifest only, without downloading zips (fast dry run)
python Water_quality_data/download_public_data_wqp.py --manifest-only --skip-counts

# Rebuild the completed-search registry from the manifest, without contacting WQP
python Water_quality_data/download_public_data_wqp.py --registry-from-manifest

# Sanity check the manifest / count summary
python Water_quality_data/test_load_public_data_wqp.py
```

`public_data_wqp_downloaded_counties.json` records completed searches so `--skip-recorded-searches` can resume without re-downloading.

---

## Step 2 — Match Locations

Matches each public row's coordinates (`ACC_X` = latitude, `ACC_Y` = longitude) to WQP monitoring stations within a **10 km** radius (`--max-nearest-km`).

**Analyte-prioritized matching (default).** For each point the matcher prefers the nearest station that actually carries major-ion chemistry (the `Inorganics, Major, Metals` group: calcium, magnesium, sodium, potassium, ...) over a *closer* physical-only station that only reports pH, conductance, or temperature. If no chemistry station is in range it falls back to the nearest station of any kind, so physical coverage is never lost. Without this, points matched whichever station was physically closest — often a continuous-monitoring site with no lab chemistry — which was the single biggest cause of missing calcium/magnesium/sodium/TDS.

The matcher also records **every** station within the radius (`wqp_nearby_station_ids`, `wqp_nearby_result_zips`), which Step 3 uses for neighborhood aggregation.

```bash
python Water_quality_data/match_public_data_wqp_locations.py

# Fast rerun: reuse station metadata already on disk, skip per-station counting
python Water_quality_data/match_public_data_wqp_locations.py --skip-station-download --skip-result-counts

# Revert to plain nearest-station matching, or change the priority group
python Water_quality_data/match_public_data_wqp_locations.py --no-analyte-priority
python Water_quality_data/match_public_data_wqp_locations.py --priority-characteristic-types "Inorganics, Major, Metals"
```

`wqp_match_method` records which rule produced each match: `nearest_priority_station` (chemistry station) or `nearest_station` (physical-only fallback).

---

## Step 3 — Merge Features

Aggregates WQP results into **one column set per analyte** and appends them to the public dataset.

**Two design decisions make the columns dense rather than sparse:**

1. **Merge fractions + convert units.** All sample fractions (`Dissolved`, `Total`, `Total Recoverable`, ...) for an analyte are merged, and every numeric value is converted to a single target unit before aggregation. Without this, one analyte fragmented across many `(characteristic, fraction, unit)` variants that were each ~99% empty.

   | Analyte group | Target unit | Conversions applied |
   |---|---|---|
   | calcium, magnesium, sodium, potassium, ... | `mg/L` | `ueq/L`/`meq/L` via per-ion equivalent weights; `ug/L` scaled |
   | conductivity, specific conductance | `uS/cm` | `mS/cm` scaled; `umho/cm`/`umho` treated as `uS/cm` |
   | salinity | `ppth` | `PSU`/`ppt` treated as equivalent |
   | temperature | `deg C` | `deg F` converted; `Temperature` and `Temperature, water` merged |
   | turbidity | `NTU` | `FNU`/`NTRU`/`JTU` treated as `NTU` |
   | pH, sodium adsorption ratio | unitless | none |

   Values in a unit that **cannot** be converted (e.g. TDS reported as `tons/day`, a load rather than a concentration) are excluded from the numeric summaries and counted in `unconvertible_count`, so incompatible units are never silently mixed.

2. **`--aggregate-nearby` (recommended).** Pools results from *every* station within the match radius instead of only the single matched station. Chemistry lives at major-ion stations and physical parameters often live at separate nearby monitoring sites, so pooling populates both for the same point.

```bash
# Recommended: pool all stations within the radius
python Water_quality_data/add_public_data_wqp_features.py --aggregate-nearby

# Single matched station only (default)
python Water_quality_data/add_public_data_wqp_features.py

# Legacy layout: one column set per (characteristic, fraction, unit), no unit conversion
python Water_quality_data/add_public_data_wqp_features.py --per-triple
```

Columns generated per analyte:

`result_count`, `activity_count`, `numeric_count`, `nondetect_count`, `unconvertible_count`, `mean`, `min`, `median`, `max`, `latest_value`, `latest_date`, `first_date`, `last_date`

**Dates are retained per analyte** (`first_date` / `last_date` / `latest_date`) plus per row (`wqp_feature_first_sample_date` / `wqp_feature_last_sample_date`). In `--aggregate-nearby` mode a `mean`/`min`/`max` summarizes the whole neighborhood over that date range — sometimes spanning decades — so use the date columns to judge temporal validity or to build date-windowed features.

`outputs/public_data_wqp_feature_manifest.csv` maps each feature stem back to its target unit, source characteristic names, merged fractions, and source units.

---

## Step 4 — Missingness Report

```bash
python Water_quality_data/print_public_data_missingness.py \
  --output Water_quality_data/outputs/public_data_wqp_feature_missingness.csv
```

Writes one row per column: `column`, `missing_count`, `total_count`, `missing_percent`.

---

## Current Results

Produced by the reproduce block above (`--aggregate-nearby`):

- Input rows: **86**
- Matched rows within 10 km: **69** (63 to a major-ion-chemistry station, 6 physical-only fallback)
- Analyte groups: **12**; WQP feature columns added: **162**
- Unmatched: 8 rows missing coordinates, 4 rows with nearest station >10 km, 5 rows with no candidate WQP data

Missing-value rates after processing. The ~20% floor is the 17 rows that cannot be matched at all (8 missing coordinates + 4 too far + 5 no candidate data), so most analytes are now at or near the best achievable rate:

| Analyte | Kind | Missing% |
|---|---|---|
| pH | physical | 19.8% |
| specific conductance | physical | 20.9% |
| temperature | physical | 20.9% |
| total dissolved solids | chemical | 20.9% |
| calcium | chemical | 22.1% |
| magnesium | chemical | 22.1% |
| sodium | chemical | 22.1% |
| turbidity | physical | 26.7% |
| conductivity | physical | 57.0% |
| salinity | physical | 61.6% |

Conductivity and salinity remain high because few stations measure them at all — that is a data-availability limit, not a pipeline gap.

---

## Adding New Data To The Public Dataset

When new facility rows are added to the public dataset, re-run the pipeline to attach water-quality features to them. The download step is incremental, so only new counties are fetched.

1. **Update both public-data CSVs.** Step 1 reads `report207appendixA_all_tables.csv` (needs `STATE`, `COUNTY`); Steps 2–3 read `report207appendixA_all_tables_labeled_acc.csv` (needs `ACC_X` latitude and `ACC_Y` longitude). New rows must appear in both, and **must have coordinates** — rows without them can never be matched.

2. **Download only the new counties.** The registry makes this incremental:

   ```bash
   python Water_quality_data/download_public_data_wqp.py --skip-recorded-searches
   ```

3. **Re-run matching and merging** (these always reprocess all rows, which is cheap):

   ```bash
   python Water_quality_data/match_public_data_wqp_locations.py
   python Water_quality_data/add_public_data_wqp_features.py --aggregate-nearby
   python Water_quality_data/print_public_data_missingness.py \
     --output Water_quality_data/outputs/public_data_wqp_feature_missingness.csv
   ```

### Things to watch for with new rows

- **`COUNTY=none` rows.** The downloader falls back to a statewide query and the matcher falls back to statewide result zips, so these still work — but statewide zips are large. If a row's county can be inferred from its coordinates, adding it to `targeted_missing_wqp_counties.csv` and downloading that county gives a tighter, faster match.
- **County name mismatches.** WQP county names must match after normalization. Known fixes live in `COUNTY_KEY_ALIASES` (e.g. `CA,SANTA MONICA` → Los Angeles County; `TX,Hildalgo` → Hidalgo County) and `INFERRED_COUNTY_KEY_BY_SOURCE_ROW` in `match_public_data_wqp_locations.py`. Check `public_data_wqp_unmatched.csv` after Step 1 — anything listed there needs an alias or a targeted download.
- **New analytes.** If you widen `--characteristic-names`, add the new characteristic to `ANALYTE_REGISTRY` (and, for ionic units, `EQUIVALENT_WEIGHT`) in `add_public_data_wqp_features.py`. Unregistered characteristics still export, but keep their unit in the column name instead of being merged into one analyte.
- **The feature column set can change.** Columns are derived from the analytes actually found at matched stations, so adding rows in a new region may add or drop columns. Re-run Step 4 and diff the missingness report to see what changed.

---

## Files And Directories

**Scripts (in pipeline order)**

- `download_public_data_wqp.py` — Step 1: batch downloader for WQP county/state result data
- `match_public_data_wqp_locations.py` — Step 2: analyte-prioritized station matcher
- `add_public_data_wqp_features.py` — Step 3: analyte aggregation, unit conversion, feature merge
- `print_public_data_missingness.py` — Step 4: per-column missing-value report
- `test_load_public_data_wqp.py` — manifest / count-summary sanity check

**Raw data**

- `wqp_result_zips/` — raw zipped WQP result CSVs, grouped by state FIPS code
- `wqp_station_zips/` — WQP monitoring-location metadata zips used for coordinate matching

**Manifests and registries**

- `public_data_wqp_manifest.csv` — one row per matched state/county search: query URL, output path, status, WQP count headers
- `public_data_wqp_unmatched.csv` — searches that could not be matched to a WQP county code
- `public_data_wqp_downloaded_counties.json` — registry of completed searches, used by `--skip-recorded-searches`
- `targeted_missing_wqp_counties.csv` — coordinate-inferred county list used to recover `COUNTY=none` rows
- `targeted_missing_wqp_manifest.csv` — manifest for those targeted recovery downloads

**Outputs**

- `outputs/public_data_wqp_count_summary.csv` — site/activity/result counts per WQP query, from response headers
- `outputs/public_data_wqp_feature_manifest.csv` — maps each feature stem to its target unit, source characteristics, merged fractions, source units
- `outputs/public_data_wqp_feature_missingness.csv` — per-column missing-value report

---

## Data Source

Water Quality Portal Result service:

- https://www.waterqualitydata.us/#advanced=true
- https://www.waterqualitydata.us/webservices_documentation/

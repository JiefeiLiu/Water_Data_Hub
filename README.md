# Brackish Water Data Hub Project

Pipelines that attach **soil** (SSURGO) and **water-quality** (Water Quality Portal) features to each desalination facility in the public dataset.

## Quick Start — Data Preprocessing

Rerun this whenever you add new facility rows to the sample data. First put the new rows (with coordinates) into **both** source files in `public_data/metadata/`:

- `report207appendixA_all_tables.csv` — needs `STATE`, `COUNTY`
- `report207appendixA_all_tables_labeled_acc.csv` — needs `ACC_X` (latitude), `ACC_Y` (longitude)

Then run, from the repo root:

```bash
# 1. Water quality: download → match → merge features
python Water_quality_data/download_public_data_wqp.py --skip-recorded-searches
python Water_quality_data/match_public_data_wqp_locations.py
python Water_quality_data/add_public_data_wqp_features.py --aggregate-nearby

# 2. Soil: download → match → build the per-mukey soil table
python Soil_data/download_public_data_ssurgo.py --skip-recorded-searches
python Soil_data/match_public_data_soil_locations.py
python Soil_data/build_soil_dimension.py

# 3. Link soil to water (adds soil_match_mukey to the water-quality features)
python public_data/link_soil_key_to_wqp_features.py
```

The two download steps are incremental — they skip counties already fetched, so a rerun only pulls data for the new rows.

## Results

| File | Contents |
|------|----------|
| `public_data/processed_data/..._wqp_features.csv` | Public data + water-quality features + `soil_match_mukey` |
| `public_data/processed_data/..._soil_location_matches.csv` | Each facility → its soil map unit (`soil_match_mukey`, `soil_match_polygon_acres`) |
| `Soil_data/outputs/soil_features_dimension.csv` | Soil profile per map unit — join on `soil_match_mukey` |

(`...` is `report207appendixA_all_tables_labeled_acc`.)

## More detail

- Water quality: [`Water_quality_data/README.md`](Water_quality_data/README.md)
- Soil: [`Soil_data/README.md`](Soil_data/README.md)
- Public dataset & feature dictionary: [`public_data/README.md`](public_data/README.md)

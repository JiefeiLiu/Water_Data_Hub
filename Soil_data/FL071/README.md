# FL071 Soil Data

This folder contains the SSURGO export for soil survey area `FL071`, Lee County, Florida. Treat it as a small relational soil database rather than a single flat feature table.

The current recommended workflow is:

1. Review the database inventory below.
2. Ask a domain expert to choose which SSURGO files/tables are useful for the project.
3. Export or join only the selected tables into analysis-ready features.
4. Add final feature-name explanations after the selected feature set is known.

## Data Inventory

FL071 contains spatial layers, soil map-unit/component/horizon tables, interpretation tables, vegetation/productivity tables, crop/yield tables, and metadata tables.

For the complete machine-readable list of exported CSVs, row counts, and column counts, use:

```text
outputs/full_database/_export_manifest.csv
```

### Spatial Data

These files describe locations and geometry. The `.shp` files store geometry, while the full-database CSV export stores the matching `.dbf` attributes.

| Layer | Files / export | What it represents |
| --- | --- | --- |
| Map-unit polygons | `spatial/soilmu_a_fl071.*`, `outputs/full_database/spatial/soilmu_a.csv` | Soil map-unit polygon areas; main layer for polygon joins to sample coordinates. |
| Map-unit lines | `spatial/soilmu_l_fl071.*`, `outputs/full_database/spatial/soilmu_l.csv` | Linear map-unit features, empty in this FL071 export. |
| Map-unit points | `spatial/soilmu_p_fl071.*`, `outputs/full_database/spatial/soilmu_p.csv` | Point map-unit features, empty in this FL071 export. |
| Survey-area polygon | `spatial/soilsa_a_fl071.*`, `outputs/full_database/spatial/soilsa_a.csv` | Boundary of the FL071 soil survey area. |
| Special feature lines | `spatial/soilsf_l_fl071.*`, `outputs/full_database/spatial/soilsf_l.csv` | Linear special soil features, empty in this FL071 export. |
| Special feature points | `spatial/soilsf_p_fl071.*`, `outputs/full_database/spatial/soilsf_p.csv` | Point special soil features. |

### Core Soil Tables

These are usually the first tables to inspect for coordinate-based matching.

| Table | File | What it contains |
| --- | --- | --- |
| Legend | `legend.csv` / `legend.txt` | Soil survey area legend information. |
| Mapunit | `mapunit.csv` / `mapunit.txt` | Map-unit records keyed by `mukey`; links spatial polygons to soil descriptions. |
| Component | `comp.csv` / `comp.txt` | Soil components within each map unit, keyed by `cokey`; includes component percentages, landform/taxonomy fields, hydric rating, slope, drainage, and related component-level properties. |
| Horizon | `chorizon.csv` / `chorizon.txt` | Horizon-level physical and chemical properties keyed by `chkey`; includes depth, texture fractions, bulk density, available water capacity, Ksat, pH, CEC, ECEC, carbonates, gypsum, SAR, EC, phosphorus, and other low/representative/high values. |

### Horizon Detail Tables

These add detail below the horizon level and usually join through `chkey`.

| Data kind | Tables |
| --- | --- |
| Texture and modifiers | `chtexgrp`, `chtextur`, `chtexmod` |
| Structure | `chstrgrp`, `chstr` |
| Fragments and pores | `chfrags`, `chpores` |
| Consistence and horizon designations | `chconsis`, `chdsuffx` |
| Engineering classifications | `chaashto`, `chunifie` |
| Horizon narrative text | `chtext` |

### Component Detail Tables

These describe component-level ecology, geomorphology, hydrology, parent material, restrictions, taxonomy, vegetation, and management information. They usually join through `cokey`.

| Data kind | Tables |
| --- | --- |
| Ecological classification and plants | `cecoclas`, `ceplants`, `ccancov` |
| Geomorphic and surface morphology | `cgeomord`, `csmorgc`, `csmorhpp`, `csmormr`, `csmorss` |
| Parent material | `cpmat`, `cpmatgrp` |
| Hydric and diagnostic features | `chydcrit`, `cdfeat` |
| Restrictions and surface fragments | `crstrcts`, `csfrags` |
| Monthly moisture, temperature, flooding, and ponding | `cmonth`, `csmoist`, `cstemp` |
| Erosion | `cerosnac` |
| Taxonomy details | `ctxfmmin`, `ctxfmoth`, `ctxmoicl` |
| Component narrative text | `ctext` |

### Productivity, Crop, And Management Tables

These are useful if the analysis needs vegetation, crop yield, forestry, or windbreak information.

| Data kind | Tables |
| --- | --- |
| Component crop yield | `ccrpyd` |
| Mapunit crop yield | `mucrpyd` |
| Forest productivity | `cfprod`, `cfprodo` |
| Trees to manage | `ctreestm` |
| Potential windbreak species | `cpwndbrk` |

### Interpretation And Soil Data Viewer Tables

These contain generated interpretations and metadata for Soil Data Viewer style attributes. They can be useful, but they are large and often need careful filtering by interpretation name or attribute.

| Data kind | Tables |
| --- | --- |
| Component interpretations | `cinterp` |
| Survey-area interpretations | `sainterp` |
| Soil Data Viewer attributes and folders | `sdvattribute`, `sdvfolder`, `sdvfolderattribute`, `sdvalgorithm` |
| Distribution metadata | `distmd`, `distlmd`, `distimd` |

### Area Overlap And Mapunit Aggregate Tables

These provide pre-aggregated or area-overlap information.

| Data kind | Tables |
| --- | --- |
| Mapunit aggregated attributes | `muaggatt` |
| Legend area overlap | `lareao` |
| Mapunit area overlap | `muareao` |
| Mapunit text | `mutext` |
| Legend text | `ltext` |

### Database Metadata Tables

These describe the database schema, domains, indexes, relationships, and column meanings. They are important for understanding table keys and valid values.

| Data kind | Tables |
| --- | --- |
| Table and column metadata | `mstab`, `mstabcol` |
| Domain metadata | `msdommas`, `msdomdet` |
| Index metadata | `msidxmas`, `msidxdet` |
| Relationship metadata | `msrsmas`, `msrsdet` |
| Survey catalog and version | `sacatlog`, `version` |

## Full Database Export

`outputs/full_database/`

This folder is a full CSV export of the FL071 SSURGO mini-database. It includes every tabular text table and every spatial DBF attribute table, with metadata-derived column names where available.

- `tabular/*.csv`: all FL071 SSURGO tabular tables.
- `spatial/*.csv`: spatial DBF attribute tables, including `soilmu_a.csv`.
- `_export_manifest.csv`: exported table list with row and column counts.

The validation run exported 74 CSV tables and 416,657 total rows. The original shapefile geometry is still stored in `spatial/*.shp`; the full database CSV export stores the spatial DBF attributes, not full polygon geometry.

To regenerate the full database CSV export, run:

```bash
python Soil_data/extract_fl071_soil_values.py --full-database --replace
```

## Analysis-Ready Sample Output

`outputs/fl071_mapunit_centroid_soil_values.csv`

This is a small example feature table, not the full database. Each row represents one FL071 map-unit polygon. The `longitude` and `latitude` fields are polygon centroid coordinates in WGS84. Soil values are taken from the dominant/major representative component for the map unit, then from that component's surface horizon.

The file has 11,761 data rows plus a header row.

Regenerate it with:

```bash
python Soil_data/extract_fl071_soil_values.py
```

## Source Files

- `spatial/soilmu_a_fl071.shp` and `spatial/soilmu_a_fl071.dbf`: map-unit polygon geometry and attributes.
- `tabular/mapunit.txt`: map-unit names and keys.
- `tabular/comp.txt`: soil components and representative component percentages.
- `tabular/chorizon.txt`: horizon depths and soil chemical attributes.
- `tabular/mstab.txt`: table-level SSURGO metadata.
- `tabular/mstabcol.txt`: column-level SSURGO metadata.

## Generation Script

The extraction script is `../extract_fl071_soil_values.py`.

Supported modes:

- Default: write one row per map-unit polygon centroid.
- `--points-csv`: append representative soil attributes to an input point CSV with longitude/latitude columns.
- `--full-database`: export every tabular table and spatial DBF attribute table to CSV files.

## Downloading Source Data

The raw SSURGO export can be downloaded with `../download_ssurgo.py` after copying the zip URL from Web Soil Survey's Download Soils Data tab:

```bash
python Soil_data/download_ssurgo.py FL071 --url "https://websoilsurvey.sc.egov.usda.gov/DSD/Download/..."
```

If Web Soil Survey has a standard cached file available, the URL can be omitted and the script will try the common SSURGO cache patterns:

```bash
python Soil_data/download_ssurgo.py FL071 --replace
```

## Sample Feature Name Reference

This section documents the current analysis-ready sample output only. After an expert selects the final SSURGO tables/features, this section should be replaced or expanded with the final feature definitions.

| Feature name | Meaning | Unit / notes |
| --- | --- | --- |
| `areasymbol` | Soil survey area symbol. For this dataset, the value is `FL071`. | Text identifier |
| `spatialver` | Spatial data version from the SSURGO map-unit polygon layer. | Version number |
| `longitude` | Longitude of the map-unit polygon centroid. | Decimal degrees, WGS84 |
| `latitude` | Latitude of the map-unit polygon centroid. | Decimal degrees, WGS84 |
| `musym` | Map-unit symbol used to identify the soil map unit within the survey. | Text identifier |
| `mukey` | Map-unit key, the unique SSURGO identifier for the map-unit record. | Text/numeric identifier |
| `muname` | Map-unit name, such as the named soil complex and slope class. | Text |
| `component_name` | Name of the selected representative soil component within the map unit. | Text |
| `component_percent_r` | Representative percentage of the selected component within the map unit. | Percent |
| `horizon_name` | SSURGO horizon designation for the selected surface horizon, such as `A`, `A1`, `E`, or `Bw`. | Text |
| `horizon_top_cm` | Representative depth from the soil surface to the top of the horizon. | Centimeters |
| `horizon_bottom_cm` | Representative depth from the soil surface to the bottom of the horizon. | Centimeters |
| `ph1to1h2o_r` | Representative soil pH measured using the 1:1 soil-water method. | pH scale |
| `ph01mcacl2_r` | Representative soil pH measured using the 0.01M calcium chloride method. | pH scale |
| `cec7_r` | Representative cation-exchange capacity at pH 7. Indicates the soil's ability to hold exchangeable cations. | Milliequivalents per 100 grams |
| `ecec_r` | Representative effective cation-exchange capacity. Calculated as extractable bases plus extractable aluminum. | Milliequivalents per 100 grams |
| `sumbases_r` | Representative sum of extractable base cations, including calcium, magnesium, potassium, and sodium. | Milliequivalents per 100 grams |
| `caco3_r` | Representative calcium carbonate equivalent in the soil fine fraction. | Percent |
| `gypsum_r` | Representative gypsum content in the soil. | Percent |
| `sar_r` | Representative sodium adsorption ratio. Describes sodium relative to calcium and magnesium in the soil-water extract. | Ratio |
| `pbray1_r` | Representative Bray 1 extractable phosphorus, often used as a plant-available phosphorus estimate. | Milligrams per kilogram |
| `poxalate_r` | Representative ammonium oxalate extractable phosphorus. | Milligrams per kilogram |
| `ph2osoluble_r` | Representative water-soluble phosphorus. | Milligrams per kilogram |
| `ptotal_r` | Representative total phosphorus content. | Percent |

SSURGO column suffixes often use `_r`, `_l`, and `_h` for representative, low, and high values. The sample output keeps representative values only, so columns ending in `_r` should be interpreted as typical values for the selected component and horizon.

Blank cells mean the attribute was not populated in the original FL071 SSURGO tabular data for that map unit, component, or horizon.

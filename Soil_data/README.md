# Soil Data Downloads

This directory contains soil survey data downloaded from the USDA NRCS Web Soil Survey / SSURGO public download service.

## Downloaded Dataset

The downloaded files are raw SSURGO soil survey zip packages. Each zip file is one SSURGO soil survey area returned by Web Soil Survey for the state and county searches derived from:

```text
public_data/report207appendixA_all_tables.csv
```

The downloader searches by state and county, then keeps every SSURGO result returned by Web Soil Survey. This means one source county can map to multiple downloaded soil survey area packages.

## Current Download Summary

- Source searches: state/county combinations from `public_data/report207appendixA_all_tables.csv`
- Source states represented in the manifest: 16
- Matched manifest rows: 1299
- Unique SSURGO zip packages: 1268
- Zip files currently on disk: 1268
- Approximate download size: 28 GB
- Processing status: raw downloads retained, plus one combined processed centroid CSV generated from the downloaded zips

## Processed Output

`outputs/public_data_ssurgo_mapunit_centroid_soil_values.csv`

This file combines all 1268 downloaded SSURGO zip packages into one CSV. Each data row represents one SSURGO map-unit polygon. The `longitude` and `latitude` values are polygon centroids in WGS84. Soil attributes are selected the same way as the `FL071/` example: the dominant/major representative component is selected for each map unit, then values are taken from that component's surface horizon.

- Data rows: 15,096,584
- File size: about 2.0 GB
- Processing errors: 0
- Error log: `outputs/public_data_ssurgo_processing_errors.csv`

The processed CSV columns are:

```text
areasymbol, spatialver, longitude, latitude, musym, mukey, muname,
component_name, component_percent_r, horizon_name, horizon_top_cm,
horizon_bottom_cm, ph1to1h2o_r, ph01mcacl2_r, cec7_r, ecec_r,
sumbases_r, caco3_r, gypsum_r, sar_r, pbray1_r, poxalate_r,
ph2osoluble_r, ptotal_r
```

## Feature Name Explanations

| Feature name | Meaning | Unit / notes |
| --- | --- | --- |
| `areasymbol` | Soil survey area symbol for the SSURGO package that supplied the row. | Text identifier |
| `spatialver` | Spatial data version from the SSURGO map-unit polygon layer. | Version number |
| `longitude` | Longitude of the map-unit polygon centroid. | Decimal degrees, WGS84 |
| `latitude` | Latitude of the map-unit polygon centroid. | Decimal degrees, WGS84 |
| `musym` | Map-unit symbol used to identify the soil map unit within the survey area. | Text identifier |
| `mukey` | Map-unit key, the unique SSURGO identifier for the map-unit record. | Text/numeric identifier |
| `muname` | Map-unit name, such as the named soil complex and slope class. | Text |
| `component_name` | Name of the selected representative soil component within the map unit. | Text |
| `component_percent_r` | Representative percentage of the selected component within the map unit. | Percent |
| `horizon_name` | SSURGO horizon designation for the selected surface horizon, such as `A`, `A1`, `E`, or `Bw`. | Text |
| `horizon_top_cm` | Representative depth from the soil surface to the top of the selected horizon. | Centimeters |
| `horizon_bottom_cm` | Representative depth from the soil surface to the bottom of the selected horizon. | Centimeters |
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

SSURGO column suffixes often use `_r`, `_l`, and `_h` for representative, low, and high values. This processed output keeps representative values only, so columns ending in `_r` should be interpreted as typical values for the selected component and surface horizon.

Blank cells mean the attribute was not populated in the original SSURGO tabular data for that map unit, component, or horizon.

## Files And Directories

- `public_data_ssurgo_zips/`: downloaded raw SSURGO zip files, grouped by survey area symbol
- `public_data_ssurgo_manifest.csv`: manifest of every matched Web Soil Survey result, including source state/county, matched county, area symbol, zip filename, local path, download status, and source URL
- `public_data_ssurgo_unmatched.csv`: searches that did not match a county in Web Soil Survey
- `download_public_data_ssurgo.py`: batch downloader used for the public-data state/county searches
- `download_ssurgo.py`: helper downloader for individual SSURGO zip packages
- `extract_public_data_ssurgo.py`: batch extractor used to generate the combined processed centroid CSV
- `outputs/public_data_ssurgo_mapunit_centroid_soil_values.csv`: combined processed CSV for all downloaded SSURGO zip packages
- `outputs/public_data_ssurgo_processing_errors.csv`: archive-level processing error log
- `FL071/`: previously extracted/downloaded SSURGO data for survey area `FL071`

## Unmatched Search

One source search did not match a Web Soil Survey county:

```text
CA,SANTA MONICA,county not found in Web Soil Survey
```

## Data Source

The data comes from USDA NRCS SSURGO through the Web Soil Survey download service:

- https://websoilsurvey.sc.egov.usda.gov/DSD/Download/help
- https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo

# Public Data Feature Dictionary

This folder contains `report207appendixA.xlsx` and CSV files generated from it by `convert_excel_tables_to_csv.py`.

The main ML-ready file is `report207appendixA_all_tables.csv`. It combines the multiple worksheet tables into one rectangular table with one shared header row. Missing source values are written as `none`.

## Features

| Feature name | Short explanation |
| --- | --- |
| **STATE** | State where the desalination facility is located. This is inferred from table sections such as Florida, California, and Texas when the source row does not include a state code. |
| **COUNTY** | County where the desalination facility is located. |
| **NAME** | Name of the desalination plant/facility. |
| **OWNER** | Organization, utility, municipality, or company that owns the facility. |
| **CITY** | City where the facility is located. |
| **TYPE** | Desalination process type, such as BWRO, NF, SWRO, EDR, MF/RO, or MF/NF. |
| **PURPOSE** | Main use of the produced water, e.g., potable water, wastewater reuse, recharge, or ASR. |
| **MGD MAX** | Maximum plant capacity in million gallons per day. |
| **START DESAL** | Year when desalination operation started. |
| **DISPOSAL CONCENTRATE** | Method used to dispose or manage concentrate/brine. |
| **WATER SOURCE** | Source water entering the plant, e.g., groundwater, surface water, seawater, or wastewater effluent. |
| **DESAL REASON / TREATMENT** | Main reason desalination is needed, such as salinity removal, softening, contaminant removal, or reuse treatment. |
| **CONCENTRATE POST-TREATMENT** | Any treatment applied to concentrate before disposal or reuse. |
| **DESAL DESIGN PRODUCTION (mgd)** | Designed desalinated-water production capacity. |
| **DESAL AVERAGE PRODUCTION (mgd)** | Actual average desalinated-water production. |
| **PLANT DESIGN PRODUCTION (mgd)** | Total designed production capacity of the whole plant, including non-desalinated water if blended. |
| **PLANT AVERAGE PRODUCTION (mgd)** | Actual average total plant production. |
| **BLENDING?** | Whether desalinated permeate is blended with another water source. |
| **RAW WATER TDS OR CONDUCTIVITY** | Salinity level of the raw/source water, standardized to mg/L TDS equivalent. |
| **PRE-TREATMENT** | Treatment before desalination, such as filtration, chemical conditioning, cartridge filtration, or microfiltration. |
| **FEED PRESSURE TO DESAL (psi)** | Operating pressure applied to feed water entering the desalination membrane system. |
| **MEMBRANE RECOVERY (%)** | Percentage of feed water converted into permeate/product water. |
| **PERMEATE TDS OR CONDUCTIVITY** | Salinity level of the desalinated product water. |
| **BLEND TDS OR CONDUCTIVITY** | Salinity level after permeate is blended with another water source. |
| **BLEND RATIO (PERMEATE : OTHER)** | Ratio between desalinated water and other water used for blending. |
| **BLEND WATER SOURCE** | Source of the non-permeate water used for blending. |
| **PERMEATE POST-TREATMENT** | Treatment applied after desalination, such as pH adjustment, remineralization, disinfection, or stabilization. |
| **AGE OF MEMBRANE / LAST REPLACEMENT (yr)** | Membrane age or time since the most recent membrane replacement. |
| **FATE OF WASTEWATER CLEANING** | Disposal destination for chemical cleaning waste from membrane maintenance. |
| **FATE OF WASTE BACKWASH** | Disposal destination for backwash waste from pretreatment or filtration systems. |
| **SOURCE SECTION** | Original worksheet/table section where the row came from. This is retained for traceability and can be dropped before modeling if not needed. |
| **SOURCE EXCEL ROW** | Original Excel row number for traceability. This can be dropped before modeling if not needed. |

## Value Conversions

The converter expands short codes in selected columns before writing the CSV files.

### TYPE

| Source value | CSV value |
| --- | --- |
| `RO` | Reverse osmosis |
| `NF` | Nanofiltration |
| `MF/RO` | Microfiltration / reverse osmosis |
| `UF/RO` | Ultrafiltration / reverse osmosis |
| `SWRO` | Seawater reverse osmosis |
| `primarily EDR (EDR/MF/RO/evap)` | primarily electrodialysis reversal (electrodialysis reversal / microfiltration / reverse osmosis / evaporation) |
| `MF/RO/AOP` | Microfiltration / reverse osmosis / advanced oxidation process |
| `RO/VSEP` | Reverse osmosis / vibratory shear enhanced processing |
| `UF/NF and NF (separate systems)` | Ultrafiltration / nanofiltration and nanofiltration (separate systems) |
| `UF/NF` | Ultrafiltration / nanofiltration |

### PURPOSE

| Source value | CSV value |
| --- | --- |
| `DW` | Drinking water |
| `WWTP` | Wastewater treatment plant |
| `WRF` | Water reclamation facility |
| `ATP (advanced treatment plant)` | Advanced treatment plant |

### WATER SOURCE

| Source value | CSV value |
| --- | --- |
| `GW` | Groundwater |
| `surface` | Surface water |
| `surface (lake)` | Surface water (lake) |
| `surface and GW` | Surface water and groundwater |
| `ocean` | Seawater |
| `WWTP` | Wastewater treatment plant |

### FATE OF WASTEWATER CLEANING

| Source value | CSV value |
| --- | --- |
| `DWI` | Deep well injection |
| `DWI (haven't cleaned yet)` | Deep well injection (haven't cleaned yet) |
| `neutralize, DWI` | neutralization, deep well injection |

### DISPOSAL CONCENTRATE

| Source value | CSV value |
| --- | --- |
| `surface` | Surface water discharge |
| `sewer` | Sewer discharge |
| `DWI` | Deep well injection |
| `EP` | Evaporation pond |
| `LA` | Land application |
| `DWI/sewer` | Deep well injection / sewer discharge |
| `EP and sewer` | Evaporation pond and sewer discharge |
| `LA sanitation` inside longer text | Los Angeles sanitation |
| `WWTP` inside longer text | wastewater treatment plant |
| `OCSD` inside longer text | Orange County Sanitation District |
| `OO` inside longer text | ocean outfall |
| `OF` inside longer text | outfall |
| `NF` inside longer text | nanofiltration |

### DESAL REASON / TREATMENT

| Source value | CSV value |
| --- | --- |
| `TDS` | total dissolved solids |
| `TOC` | total organic carbon |
| `H2S` | hydrogen sulfide |
| `THM` | trihalomethane |
| `THMs` | trihalomethanes |
| `HAA` or `HAA%` | haloacetic acids |
| `SO4` | sulfate |
| `NH3` | ammonia |
| `Fe` | iron |
| `Mn` | manganese |
| `As` | arsenic |
| `F` | fluoride |
| `IX` | ion exchange |
| `LS` | lime softening |
| `IPR` | indirect potable reuse |
| `DW` | drinking water |

Blank output cells in all columns are converted to `none`.

## Unit Standardization

`RAW WATER TDS OR CONDUCTIVITY` contains values reported as both TDS concentration and electrical conductivity. The converter standardizes numeric values to `mg/L TDS equivalent`.

| Source unit or format | CSV format |
| --- | --- |
| `mg/l`, `mg/L`, or typo-like `g/l` values in this column | Treated as mg/L TDS and written as `mg/L TDS equivalent`. |
| `µS/cm` or `uS/cm` conductivity values | Converted using `TDS mg/L = conductivity µS/cm * 0.64`, then written as `mg/L TDS equivalent`. |
| Numeric values without an explicit unit | Treated as mg/L TDS because they appear in the raw-water TDS/conductivity column. |
| Text-only values such as `depends on wells used` or `no` | Written as `none` because no numeric value can be standardized. |

## Regenerating CSV Files

Run this command from the repository root:

```bash
python public_data/convert_excel_tables_to_csv.py
```

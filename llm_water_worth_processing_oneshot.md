# LLM Example — One-Shot Prompt (Is the Source Water Worth Processing?)

A **one-shot** version of the water-worth-processing prompt. It gives the model one
fully worked, labeled example (a *positive* case — an already-built, operating plant)
before asking it to assess a new target site.

Both records use **public facility data + water-quality features** from
`public_data/processed_data/report207appendixA_all_tables_labeled_acc_wqp_features.csv`.
Soil data is excluded from this test.

## Why one-shot works here

Every row in our dataset is an **operating** desalination plant, so each is an implicit
**positive label**: the water *was* judged worth processing. We use one such plant as the
exemplar (with a worked "worth processing" answer), which teaches the model both the
desired reasoning and the exact output format before it evaluates the target.

## Records used

- **Exemplar (the "shot"):** `SOURCE EXCEL ROW = 18` — City of Hialeah RO WTP (Miami-Dade, FL).
- **Target (the query):** `SOURCE EXCEL ROW = 26` — North Cape Coral RO WTP (Lee, FL).

They are **similar**: both are large Florida brackish-**groundwater** RO drinking-water
plants using deep-well concentrate injection, with near-identical near-site chemistry
(median TDS ≈ 338 vs 323 mg/L, salinity ≈ 0.31 vs 0.30 ppth, calcium ≈ 84 vs 82 mg/L) —
a good analog, in an independent county.

Both are shown **blind**: operational/outcome fields (chosen process, recovery, feed
pressure, permeate TDS, blending, start year, membrane age, pre/post-treatment) are
withheld; only up-front decision context and the source-water quality are given.

## The Prompt

```text
You are a desalination and water-treatment analyst. Your job is to assess whether a
proposed source water is worth processing (desalinating/treating) to meet a stated
water-supply purpose, based on the site context and the water quality measured near it.

"Worth processing" means: weighing the source-water salinity and chemistry against a
suitable treatment approach, achievable recovery, energy demand, fouling/scaling risk,
concentrate disposal, and the value/volume of product water — is treating this water a
sound investment, or would the cost, risk, or disposal burden make it a poor choice?

For each site answer with:
1. VERDICT: {Worth processing, Marginal, Not worth processing}.
2. CONFIDENCE: High / Medium / Low.
3. RECOMMENDED PROCESS: if worth processing, the treatment approach that fits this water
   (e.g. brackish-water RO, nanofiltration, ...) and a rough achievable recovery.
4. KEY REASONS: 3–6 bullets citing specific numbers.
5. RISKS & CAVEATS: fouling/scaling, salinity variability, concentrate disposal, and that
   the water data is a ~10 km neighborhood aggregate over decades, not the actual intake.
6. WHAT DATA WOULD MOST REDUCE UNCERTAINTY.

Use the median as "typical" and the range as the envelope. Where data is sparse (small n),
say so rather than guessing.

════════════════════════════════════════════════════════════════════════
EXAMPLE
════════════════════════════════════════════════════════════════════════
SITE CONTEXT
  Facility / site:               City of Hialeah water supply site
  Owner:                         City of Hialeah Water and Sewer Department
  Location:                      Hialeah, Miami-Dade County, FL (lat 25.8285, lon -80.2861)
  Intended purpose:              Public drinking-water supply
  Source water:                  Brackish groundwater
  Treatment goal:                Reduce total dissolved solids (TDS) to potable levels
  Needed capacity:               ~7.5 MGD
  Available concentrate disposal: deep well injection

SOURCE WATER QUALITY  (aggregate of 673 WQP stations within ~10 km, 1907–2025, 116,755 results)
  Analyte                     Typical(median)  Mean     Range (min–max)     n        Years
  --------------------------- ---------------  ------   -----------------   ------   ---------
  Total dissolved solids      338 mg/L         557      0 – 31,700          4,945    1907–2025
  Specific conductance        660 µS/cm        4,941    0 – 376,665         33,386   1923–2025
  Salinity                    0.31 ppth        3.97     0 – 98.65           18,741   1994–2025
  Calcium                     84 mg/L          90       0.02 – 2,020        1,794    1907–2025
  Magnesium                   7.78 mg/L        17.8     0.001 – 1,180       1,805    1907–2025
  Sodium                      32 mg/L          78       0.8 – 4,400         1,397    1907–2025
  Potassium                   2.5 mg/L         5.4      0 – 145             1,379    1930–2025
  Sodium + potassium          11 mg/L          209      0.8 – 10,000        388      1920–1980
  pH                          7.46             7.49     0.8 – 25.2          21,416   1940–2025
  Water temperature           26.1 °C          25.9     0.2 – 741           24,106   1930–2025
  Turbidity                   1.2 NTU          3.9      0 – 530             7,397     1907–2025

ASSESSMENT
  1. VERDICT: Worth processing.
  2. CONFIDENCE: High.
  3. RECOMMENDED PROCESS: Single-pass brackish-water reverse osmosis (BWRO) with acid +
     antiscalant pretreatment; ~75–85% recovery is realistic for this salinity.
  4. KEY REASONS:
     - Brackish, not seawater: near-site median salinity ~0.31 ppth and reported raw TDS
       ~3,200–3,520 mg/L sit squarely in the BWRO range — far cheaper/lower-pressure than
       seawater RO.
     - Scaling is manageable: calcium ~84 mg/L (median) with moderate hardness means CaCO3
       scaling is controllable with acid/antiscalant rather than a deal-breaker.
     - Warm, stable groundwater (~26 °C) improves membrane flux and lowers energy per gallon.
     - High-value, steady product: potable supply at ~7.5 MGD municipal demand justifies the
       treatment cost.
     - Concentrate disposal is solved: deep well injection is available on site.
  5. RISKS & CAVEATS: the wide TDS/conductance range (max TDS 31,700; SC 376,665) reflects
     saltwater intrusion at depth, so the true feed salinity depends on well depth; Ca/Mg
     scaling and Florida-aquifer H2S need pretreatment; this chemistry is a ~10 km,
     multi-decade neighborhood aggregate, not the plant intake.
  6. WHAT DATA WOULD MOST REDUCE UNCERTAINTY: a direct feed-water analysis from the
     production wells at intake depth (TDS, major ions, hardness/LSI, H2S).

════════════════════════════════════════════════════════════════════════
NOW ASSESS THIS SITE
════════════════════════════════════════════════════════════════════════
SITE CONTEXT
  Facility / site:               North Cape Coral water supply site
  Owner:                         City of Cape Coral Utilities Department
  Location:                      Cape Coral, Lee County, FL (lat 26.6957, lon -81.9992)
  Intended purpose:              Public drinking-water supply
  Source water:                  Brackish groundwater
  Treatment goal:                Reduce total dissolved solids (TDS) to potable levels
  Needed capacity:               ~12 MGD
  Available concentrate disposal: deep well injection

SOURCE WATER QUALITY  (aggregate of 733 WQP stations within ~10 km, 1946–2025, 133,020 results)
  Analyte                     Typical(median)  Mean     Range (min–max)     n        Years
  --------------------------- ---------------  ------   -----------------   ------   ---------
  Total dissolved solids      323 mg/L         2,987    0.5 – 281,610       4,238    1946–2025
  Specific conductance        593 µS/cm        5,070    0 – 529,000         26,605   1946–2025
  Salinity                    0.3 ppth         5.1      0 – 74.5            23,270   1980–2025
  Calcium                     81.8 mg/L        89.5     10.5 – 714          1,337    1946–2025
  Magnesium                   7.4 mg/L         25.2     1.4 – 1,100         1,337    1946–2025
  Sodium                      68 mg/L          318      7.2 – 8,820         199      1968–2024
  Potassium                   6.9 mg/L         15.7     0.28 – 323          199      1968–2024
  Sodium + potassium          295 mg/L         295      140 – 450           2        1946
  pH                          7.79             7.77     1.1 – 10.5          26,609   1946–2025
  Water temperature           25.8 °C          25.1     -10.2 – 52.1        27,416   1946–2025
  Turbidity                   2.15 NTU         4.0      0.01 – 1,398        21,806   1975–2025
  Conductivity                332 µS/cm        332      51.6 – 613          2        2014–2021

ASSESSMENT:
```

## Notes

- The exemplar's ASSESSMENT block is a *worked positive answer*; it teaches the model the
  reasoning depth and output format. Swap in a negative/marginal exemplar later to balance
  the framing if the model over-predicts "worth processing."
- Numbers are rounded for readability; the source CSV holds full precision.
- Water-quality features are the `--aggregate-nearby` WQP outputs (all stations within
  ~10 km), so each value is a neighborhood-and-multi-decade summary, not a single intake.

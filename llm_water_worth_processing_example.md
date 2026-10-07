# LLM Example — Is the Source Water Worth Processing?

A worked example of using an LLM to assess whether a plant's source water is worth
desalinating, using **public facility data + water-quality features** from
`public_data/processed_data/report207appendixA_all_tables_labeled_acc_wqp_features.csv`.
Soil data is intentionally excluded from this initial test.

## Sample

- **Row:** `SOURCE EXCEL ROW = 26`
- **Facility:** North Cape Coral RO WTP, Cape Coral, Lee County, FL
- **Why chosen:** a brackish groundwater source (~2,700 mg/L TDS) with all 12
  water-quality analytes populated — a natural "worth processing?" decision.

## Blind design

This is the **blind** variant: fields that reveal the plant already operates
successfully are withheld, so the model judges the source water on its merits
rather than reverse-engineering a known outcome.

- **Kept** (genuine up-front decision context): location, owner, intended purpose,
  source-water type, treatment goal, needed capacity, available concentrate
  disposal, and the full source-water quality.
- **Withheld** (operational / outcome fields): chosen process type, start year,
  membrane recovery, feed pressure, permeate TDS, blending ratio, pre-treatment,
  permeate/concentrate post-treatment, membrane age, and actual average production.

## The Prompt

```text
You are a desalination and water-treatment analyst. Your job is to assess whether a
proposed source water is worth processing (desalinating/treating) to meet a stated
water-supply purpose, based on the site context and the water quality measured near it.

"Worth processing" means: weighing the source-water salinity and chemistry against a
suitable treatment approach, achievable recovery, energy demand, fouling/scaling risk,
concentrate disposal, and the value/volume of product water — is treating this water a
sound investment, or would the cost, risk, or disposal burden make it a poor choice?

────────────────────────────────────────────────────────────────────────
SITE CONTEXT
────────────────────────────────────────────────────────────────────────
Facility / site:             North Cape Coral water supply site
Owner:                       City of Cape Coral Utilities Department
Location:                    Cape Coral, Lee County, FL  (lat 26.6957, lon -81.9992)
Intended purpose:            Public drinking-water supply
Source water:                Brackish groundwater
Treatment goal:              Reduce total dissolved solids (TDS) to potable levels
Needed capacity:             ~12 MGD
Available concentrate disposal: deep well injection

(No treatment process has been assumed. Recommend one if the water is worth processing.)

────────────────────────────────────────────────────────────────────────
SOURCE WATER QUALITY (near the site)
────────────────────────────────────────────────────────────────────────
These values aggregate every Water Quality Portal result from 733 monitoring
stations within ~10 km of the site, sampled 1946-03-22 to 2025-08-12 (133,020
results). This characterizes the neighborhood's water, NOT a single intake. Wide
ranges reflect many wells at different depths and varying seawater intrusion; use
the median as "typical" and the range as the envelope.

Analyte                     Typical (median)   Mean      Range (min–max)     n       Years
--------------------------- ----------------   -------   -----------------   -----   ---------
Total dissolved solids      323 mg/L           2,987     0.5 – 281,610       4,238   1946–2025
Specific conductance        593 µS/cm          5,070     0 – 529,000         26,605  1946–2025
Salinity                    0.3 ppth           5.1       0 – 74.5            23,270  1980–2025
Calcium                     81.8 mg/L          89.5      10.5 – 714          1,337   1946–2025
Magnesium                   7.4 mg/L           25.2      1.4 – 1,100         1,337   1946–2025
Sodium                      68 mg/L            318       7.2 – 8,820         199     1968–2024
Potassium                   6.9 mg/L           15.7      0.28 – 323          199     1968–2024
Sodium + potassium          295 mg/L           295       140 – 450           2       1946
pH                          7.79               7.77      1.1 – 10.5          26,609  1946–2025
Water temperature           25.8 °C            25.1      -10.2 – 52.1        27,416  1946–2025
Turbidity                   2.15 NTU           4.0       0.01 – 1,398        21,806  1975–2025
Conductivity                332 µS/cm          332       51.6 – 613          2       2014–2021

────────────────────────────────────────────────────────────────────────
QUESTION
────────────────────────────────────────────────────────────────────────
Is this source water worth processing to supply drinking water at this site? Answer with:

1. VERDICT: one of {Worth processing, Marginal, Not worth processing}.
2. CONFIDENCE: High / Medium / Low, given the data quality and spread.
3. RECOMMENDED PROCESS: if worth processing, the treatment approach that fits this
   water (e.g. brackish-water RO, nanofiltration, ...) and a rough achievable recovery.
4. KEY REASONS: 3–6 bullets citing specific numbers above (salinity class, scaling
   ions such as calcium/magnesium, temperature, how the chemistry fits the process).
5. RISKS & CAVEATS: fouling/scaling, seawater-intrusion variability, concentrate
   disposal, and the fact that this data is a ~10 km neighborhood aggregate over
   decades rather than the actual intake.
6. WHAT DATA WOULD MOST REDUCE UNCERTAINTY: the single most useful measurement or
   record to confirm the assessment.

Base your reasoning only on the information above. Where the data is ambiguous or too
sparse (small n), say so rather than guessing.
```

## Ground Truth (held out — for evaluation only, NOT part of the prompt)

The query site (row 26, North Cape Coral RO WTP) is a real, operating plant, so its actual
data is the ground truth to compare against the LLM's answer. These include the operational
fields withheld from the blind prompt. **Do not include this block in the prompt.**

```text
GROUND TRUTH — North Cape Coral RO WTP (row 26), Cape Coral, Lee County, FL
  Verdict:              WORTH PROCESSING — the plant was built and has operated since 2010
  Process:              reverse osmosis (brackish-water RO)
  Purpose:              drinking water | Source: groundwater
  Raw water TDS:        ~2,700 mg/L
  Capacity:             12 MGD max / 12 MGD desal design; 8.5 MGD average plant production
  Recovery:             80%
  Feed pressure:        160 psi
  Pre-treatment:        acid, antiscalant, cartridge filters
  Blending:             yes — 15–25% raw bypass
  Permeate TDS:         100–118 mg/L
  Post-treatment:       blend, degasification, chlorine (disinfection + residual H2S
                        removal), caustic (pH adjustment)
  Concentrate:          deep well injection (neutralized first)
  Cleaning waste:       neutralization, deep well injection
  Membranes:            original membranes still in service
```

Compare the LLM output to the ground truth on:

| Output item | What to check against the ground truth |
|---|---|
| VERDICT | Should be "Worth processing" (the plant exists and runs at 8.5 MGD). |
| RECOMMENDED PROCESS | Brackish-water RO at roughly 80% recovery. |
| KEY REASONS | Brackish feed (~2,700 mg/L) suits BWRO; deep-well injection available for concentrate. |
| RISKS & CAVEATS | Scaling control (the real plant uses acid + antiscalant); H2S (real plant degasifies). |

Caveat: every row in the dataset is an operating plant, so the verdict is always "Worth
processing". The verdict alone cannot tell a good model from one that always says yes; the
process and recovery comparison is the more informative test.

## Notes

- Numbers are rounded for readability; the source CSV holds full precision.
- The water-quality features come from the WQP pipeline
  (`Water_quality_data/`), aggregated across all stations within ~10 km
  (`--aggregate-nearby`), so each value is a neighborhood-and-multi-decade summary.
- To reproduce which fields exist for a row, read the row from the processed CSV;
  facility columns are the non-`wqp_` fields and water-quality features are the
  `wqp_<analyte>_*` columns.

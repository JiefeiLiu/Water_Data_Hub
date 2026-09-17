# LLM Example — Three-Shot RAG Treatment Recommendation

A RAG-grounded prompt: instead of a fixed verdict template, the model recommends **how to
process** a site's source water, grounded in the **three most similar existing plants**
retrieved from the public dataset. A **similarity threshold** decides whether those
retrieved plants are close enough to serve as references.

- **Retrieval:** `rag_sample_extraction/extract_rag_samples.py` (hard filters on purpose +
  source water + process family, then weighted similarity on the 30-year analyte medians).
- **Query:** `SOURCE EXCEL ROW = 26` — North Cape Coral (shown blind: process not revealed).
- **References (top 3):** rows 18, 19, 23 with similarity 0.75 / 0.74 / 0.73.
- **Threshold:** `0.50` (tunable). All three references clear it, so they are included; if
  the best match fell below 0.50 the prompt switches to the no-reference fallback (shown at
  the end).

The references are shown **in full**, including how each plant treats its water (that is the
signal the model learns from). The query is **blind** — its treatment train is withheld,
because recommending it is the task.

## Water-quality data provenance (important for the pilot)

Water quality appears for **both** sides, from **two different sources**:

- **Query site — user-provided.** In the pilot the user supplies the query site's water
  quality (e.g. intake/well analyses, or their own local monitoring). This is typically a
  more direct, site-specific measurement of the actual feed water.
- **Reference plants — from our database.** Each reference's water quality is the 30-year,
  ~10 km neighborhood aggregate the WQP pipeline produced (medians as "typical", with a
  min–max envelope).

Both feed the process: the user's query water quality drives **retrieval** (it is compared
against the database examples to find the three most similar) **and** appears in the prompt
so the model can reason over it. Because the two sources differ in provenance (a direct
intake analysis vs. a neighborhood aggregate), the prompt tells the model to weigh them
accordingly. In the illustrative example below, row 26's aggregated stats stand in for the
user-provided query values.

## The Prompt

```text
You are a desalination and water-treatment analyst. Recommend HOW to treat the source water
at the query site to meet its stated purpose. Ground your recommendation in the reference
plants provided — real, operating facilities retrieved as the most similar to the query by
source-water chemistry, water source, intended purpose, and process family. Prefer choices
that the references actually use over generic textbook defaults, and say which reference(s)
support each choice. Do not output a fixed verdict; reason from the references.

Reference quality — each reference has a similarity score in [0,1] (1 = identical):
- References shown below all passed the inclusion threshold of 0.50, so treat them as
  relevant analogs. The higher the score, the more weight it deserves.
- If NO reference had passed the threshold, you would be told "No similar reference plants
  found"; in that case, recommend from first principles and state explicitly that the
  recommendation has no reference support.

Data provenance — the query site's water quality is provided by the user (typically a direct
intake/well analysis of the actual feed), while each reference's water quality is a 30-year,
~10 km neighborhood aggregate from a database (median = typical, with a min–max envelope).
Treat the user's query values as the more direct measurement of the feed; use the reference
water quality mainly to judge how alike each analog is, not as ground truth for the query.

════════════════════════════════════════════════════════════════════════
REFERENCE PLANTS (3 most similar; all above the 0.50 threshold)
════════════════════════════════════════════════════════════════════════
[R1] City of Hialeah RO WTP — Hialeah, Miami-Dade, FL   | similarity 0.75
  Purpose: drinking water | Source: brackish groundwater | Raw TDS: 3,200–3,520 mg/L
  Source water (30-yr near-site median [min–max]): TDS 330 [0.2–25,200] mg/L; salinity
    0.31 [0–98.7] ppth; calcium 71 [20–2,020]; magnesium 9.8; sodium 38; pH 7.5; temp 26 °C
  HOW IT IS TREATED:
    Process: brackish-water reverse osmosis (BWRO) | Recovery: 80% | Feed pressure: 180–194 psi
    Pre-treatment: acid, antiscalant, cartridge filters | Blending: none
    Post-treatment: lime, caustic, chlorine | Concentrate: deep well injection

[R2] Town of Davie WTP/WRF — Davie, Broward, FL          | similarity 0.74
  Purpose: drinking water | Source: brackish groundwater | Raw TDS: 4,480–5,760 mg/L
  Source water (30-yr near-site median [min–max]): TDS 356 [99–14,500] mg/L; salinity
    0.35 [0–37.9] ppth; calcium 68; magnesium 10; sodium 47; pH 7.6; temp 26.5 °C
  HOW IT IS TREATED:
    Process: brackish-water reverse osmosis (BWRO) | Recovery: 80% | Feed pressure: 230 psi
    Pre-treatment: antiscalant, cartridge filters | Blending: none | Permeate TDS: 300–450 mg/L
    Post-treatment: aeration, hypochlorite disinfection, fluoride | Concentrate: deep well injection

[R3] Springtree — Broward, FL                            | similarity 0.73
  Purpose: drinking water | Source: brackish groundwater | Raw TDS: 1,605 mg/L
  Source water (30-yr near-site median [min–max]): TDS 357 [129–29,700] mg/L; salinity
    0.27 [0–31.7] ppth; calcium 56; magnesium 10; sodium 46; pH 7.6; temp 26 °C
  HOW IT IS TREATED:
    Process: brackish-water reverse osmosis (BWRO) | Recovery: 75% | Feed pressure: ~160 psi
    Pre-treatment: antiscalant, cartridge filters | Blending: 1.5:11 permeate:bypass
    Permeate TDS: 55 mg/L | Post-treatment: degasification, chloramination, fluoridation
    Concentrate: deep well injection

════════════════════════════════════════════════════════════════════════
QUERY SITE (recommend how to treat this water)
════════════════════════════════════════════════════════════════════════
  Site: North Cape Coral water supply site — Cape Coral, Lee County, FL (lat 26.696, lon -81.999)
  Owner: City of Cape Coral Utilities Department
  Purpose: public drinking-water supply | Source: brackish groundwater
  Treatment goal: reduce TDS to potable levels | Needed capacity: ~12 MGD
  Available concentrate disposal: deep well injection
  Source water (USER-PROVIDED for this site; here the row-26 30-yr near-site aggregate stands
  in — median [min–max]): TDS 318 [0.5–281,610] mg/L; salinity 0.30 [0–74.5] ppth; specific
  conductance 604 [2–59,000] µS/cm; calcium 84 [11–714] mg/L; magnesium 7 [1.4–1,100] mg/L;
  sodium 29 [7–8,820] mg/L; pH 7.8 [1.1–10.5]; temperature 25.8 °C; turbidity 2.2 NTU
  (No treatment process has been chosen — recommend one.)

════════════════════════════════════════════════════════════════════════
OUTPUT
════════════════════════════════════════════════════════════════════════
Write:
1. RECOMMENDED TREATMENT TRAIN: process, target recovery, pre-treatment, concentrate
   handling, and product post-treatment — as a short ordered list.
2. GROUNDING: for each major choice, name the reference(s) [R1/R2/R3] that support it and
   note where the query differs from them.
3. CONFIDENCE & REFERENCE MATCH: how well the references fit this query (use the similarity
   scores and how alike the source waters are), and note that the query water quality is
   user-provided while the reference water quality is a database aggregate.
4. RISKS & UNCERTAINTIES: scaling/fouling, salinity variability, the provenance difference
   between the user-provided query values and the reference aggregates, and (for any value
   drawn from a ~10 km / 30-year aggregate) that it is not a single intake measurement.
5. DATA TO CONFIRM: the single most useful measurement to verify the recommendation.
```

## Fallback variant — no reference clears the threshold

When retrieval finds nothing above the threshold (the best similarity < 0.50), the
`REFERENCE PLANTS` block is replaced by the line below and the output must flag the absence
of references. Everything else (the query block, the output structure) stays the same.

```text
════════════════════════════════════════════════════════════════════════
REFERENCE PLANTS
════════════════════════════════════════════════════════════════════════
No similar reference plants found: no plant in the dataset passed the 0.50 similarity
threshold for this query (best match: <score>). Recommend a treatment approach from first
principles and state clearly that this recommendation is NOT supported by any reference
plant, so it carries lower confidence and should be validated against site-specific data.
```

## Ground Truth (held out — for evaluation only, NOT part of the prompt)

The query site (row 26, North Cape Coral RO WTP) is a real operating plant, so how it
actually treats its water is the ground-truth answer to "how to process this water." These
are exactly the operational fields withheld to keep the query blind. **Do not include this
block in the prompt** — the model never sees it; use it only to score the model's
`RECOMMENDED TREATMENT TRAIN` against what the plant really does.

```text
GROUND TRUTH — North Cape Coral RO WTP (row 26), in operation since 2010
  Process:            brackish-water reverse osmosis (BWRO)
  Recovery:           80%
  Feed pressure:      160 psi
  Pre-treatment:      acid, antiscalant, cartridge filters
  Blending:           yes — 15–25% raw bypass blended into product
  Permeate TDS:       100–118 mg/L
  Post-treatment:     blend, degasification, chlorine (disinfection + residual H2S removal),
                      caustic (pH adjustment)
  Concentrate:        deep well injection (concentrate neutralized first)
```

Suggested comparison axes when scoring an AI output against this: process choice, recovery
target, pre-treatment train, concentrate handling, and product post-treatment. Note the
references (R1–R3) share this same BWRO + antiscalant/cartridge + deep-well-injection
pattern, so a well-grounded recommendation should land close to the ground truth here; a
future query whose true answer diverges from its references is the more informative test.

## Notes

- Threshold `0.50` is a starting value (`similarity = 1/(1+distance)`, so 0.50 ≈ one standard
  deviation of average analyte difference). Calibrate it once the expert reviews a few
  retrievals; it lives in the retrieval layer, not the model.
- References include their treatment trains on purpose — that operational detail is the RAG
  signal. The query stays blind.
- Numbers are rounded; the source CSV holds full precision. Source-water stats use the
  30-year window and are neighborhood aggregates (medians are the "typical", ranges show the
  envelope; large maxima are far-well / seawater-intrusion outliers).

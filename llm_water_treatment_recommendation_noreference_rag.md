# LLM Example — RAG Treatment Recommendation (A/B Test · Variant A: no references)

**Controlled A/B test, variant A.** All variants use the **same query as the three-shot
prompt** — row 26, North Cape Coral RO WTP — and the **same held-out ground truth**, so only
the *reference condition* changes between them:

- **Three-shot** (`llm_water_treatment_recommendation_threeshot_rag.md`): 3 **strong**
  references (row 26's real top matches, similarity 0.73–0.75).
- **Variant A (this file): no references** — the prompt provides none; the model must
  recommend from first principles and say so.
- **Variant B** (`llm_water_treatment_recommendation_weakref_rag.md`): 2 **low-similarity**
  references (row 26's dissimilar matches, similarity ~0.28–0.33), labeled LOW SIMILARITY.

Holding the query and ground truth fixed isolates one question: **do references help or
mislead, and does a weak reference beat none?** Score each variant's output against the same
ground truth. (In production, "no references" is the branch taken when retrieval finds
nothing above the 0.50 threshold; here it is applied to row 26 as a controlled condition.)

## Water-quality data provenance (important for the pilot)

- **Query site — user-provided.** In the pilot the user supplies the query site's water
  quality (intake/well analyses, or local monitoring). Here row 26's 30-year near-site
  aggregate stands in.
- **Reference plants — from our database.** None are provided in this variant.

## The Prompt

```text
You are a desalination and water-treatment analyst. Recommend HOW to treat the source water
at the query site to meet its stated purpose. Reference plants may be provided — real,
operating facilities retrieved as the most similar to the query. Do not output a fixed
verdict; reason from the evidence and say which reference(s), if any, support each choice.

Reference quality — each reference carries a similarity score in [0,1] (1 = identical):
- References at or above 0.50 are relevant analogs; weight higher scores more.
- References below 0.50 are LOW SIMILARITY — directional context only.
- If NO references are provided, recommend from first principles and state explicitly that
  the recommendation has no reference support, so it carries lower confidence.

Data provenance — the query site's water quality is user-provided (a direct intake/well
analysis of the actual feed); any reference's water quality is a 30-year, ~10 km neighborhood
aggregate from a database. Treat the user's query values as the more direct measurement.

════════════════════════════════════════════════════════════════════════
REFERENCE PLANTS
════════════════════════════════════════════════════════════════════════
No reference plants are provided for this query. Recommend a treatment approach from first
principles and state clearly that this recommendation is NOT supported by any reference
plant, so it carries lower confidence and should be validated against site-specific data.

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
2. GROUNDING: say that no references were provided and that each choice rests on
   first-principles reasoning.
3. CONFIDENCE: note that, with no references, confidence is limited; note the query water
   quality is user-provided.
4. RISKS & UNCERTAINTIES: scaling/fouling, salinity variability, and that the source-water
   data is a ~10 km / 30-year aggregate, not a single intake measurement.
5. DATA TO CONFIRM: the single most useful measurement to verify the recommendation.
```

## Ground Truth (held out — for evaluation only, NOT part of the prompt)

Same ground truth across all variants — the real treatment train of the query plant (row 26,
North Cape Coral RO WTP). **Do not include this block in the prompt**; use it only to score
the model's `RECOMMENDED TREATMENT TRAIN`.

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

## What this A/B test is meant to reveal

With the query and ground truth fixed, compare each variant's recommendation to the ground
truth on: process, **recovery target**, pre-treatment, concentrate handling, and
post-treatment. Key expectations to check:

- **Three-shot** should land closest (its strong references share the BWRO + 75–80% recovery
  + deep-well-injection pattern of the ground truth).
- **Variant A (no references)** tests first-principles reasoning alone — a baseline.
- **Variant B (weak references)** tests whether low-similarity analogs help or mislead; e.g.
  its references run lower recovery (71%) and non-deep-well concentrate disposal, which could
  pull the recommendation away from the ground truth's 80% / deep-well injection.

The most informative comparison is **A vs. B**: does showing weak, dissimilar references do
better or worse than showing none?

## Notes

- Threshold `0.50` and the LOW-SIMILARITY band are starting values; calibrate in the retrieval
  layer. This file applies the no-reference condition to row 26 for a controlled comparison.
- The instruction, query, and output blocks match the three-shot prompt and variant B; only
  the `REFERENCE PLANTS` block differs, so one template serves all cases.
- Numbers are rounded; the source CSV holds full precision. Query source-water stats use the
  30-year window and are neighborhood aggregates (median = typical; large maxima are far-well
  / seawater-intrusion outliers).

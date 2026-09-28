# LLM Example — RAG Treatment Recommendation (A/B Test · Variant A: hide weak references)

**A/B test, variant A.** Both variants use the same query (row 71, best RAG similarity
0.491 < 0.50 threshold). This variant, **A**, *hides* the weak sub-threshold matches: the
prompt carries **no reference examples** and the model must recommend from first principles
while stating the recommendation is unreferenced. Variant **B**
(`llm_water_treatment_recommendation_weakref_rag.md`) instead *shows* the nearest 1–2 weak
matches, labeled low-similarity. Score both outputs against the same held-out ground truth
to see whether showing weak references helps or misleads.

Same task and format as `llm_water_treatment_recommendation_threeshot_rag.md`, but for the
case where **RAG finds no sufficiently similar plant** (best similarity < 0.50).

- **Retrieval:** `rag_sample_extraction/extract_rag_samples.py` (hard filters on purpose +
  source water + process family, then weighted similarity on the 30-year analyte medians).
- **Query:** `SOURCE EXCEL ROW = 71` — City of Benjamin RO WTP, TX (shown blind).
- **Threshold:** `0.50`. The best candidate scored **0.491** (< 0.50), so **no reference
  passes** — even though same-class plants exist (drinking-water / groundwater / RO), none
  is chemically close: this is an unusually saline, high-hardness inland brackish
  groundwater (near-site median TDS ~7,700 mg/L, sodium ~1,700, calcium ~700), far from the
  ~300–400 mg/L brackish plants that dominate the dataset.

## Water-quality data provenance (important for the pilot)

- **Query site — user-provided.** In the pilot the user supplies the query site's water
  quality (intake/well analyses, or local monitoring). Here row 71's 30-year near-site
  aggregate stands in — and note it rests on only **3 nearby stations**, so it is itself
  sparse and uncertain.
- **Reference plants — from our database.** Normally the three most similar plants would be
  shown here in full; in this case none cleared the similarity threshold, so there are none.

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
REFERENCE PLANTS
════════════════════════════════════════════════════════════════════════
No similar reference plants found: no plant in the dataset passed the 0.50 similarity
threshold for this query (best match: 0.491). Recommend a treatment approach from first
principles and state clearly that this recommendation is NOT supported by any reference
plant, so it carries lower confidence and should be validated against site-specific data.

════════════════════════════════════════════════════════════════════════
QUERY SITE (recommend how to treat this water)
════════════════════════════════════════════════════════════════════════
  Site: City of Benjamin water supply site — Benjamin, Knox County, TX (lat 33.581, lon -99.792)
  Owner: City of Benjamin
  Purpose: public drinking-water supply | Source: brackish groundwater
  Treatment goal: reduce TDS to potable levels | Needed capacity: ~0.07 MGD (small system)
  Available concentrate disposal: (arid inland site; no deep-well option stated)
  Source water (USER-PROVIDED for this site; here the row-71 30-yr near-site aggregate from
  only 3 stations stands in — median [min–max]): TDS 7,680 [457–21,800] mg/L; specific
  conductance 11,200 [693–42,300] µS/cm; sodium 1,745 [25–8,233] mg/L; calcium 699
  [81–1,697] mg/L; magnesium 234 [11–528] mg/L; pH 7.9 [6.8–8.5]; temperature 20.5 °C;
  turbidity ~32 NTU (single reading)
  (No treatment process has been chosen — recommend one.)

════════════════════════════════════════════════════════════════════════
OUTPUT
════════════════════════════════════════════════════════════════════════
Write:
1. RECOMMENDED TREATMENT TRAIN: process, target recovery, pre-treatment, concentrate
   handling, and product post-treatment — as a short ordered list.
2. GROUNDING: for each major choice, name the reference(s) [R1/R2/R3] that support it and
   note where the query differs from them. (If no references were provided, say so here and
   state that each choice rests on first-principles reasoning, not a reference plant.)
3. CONFIDENCE & REFERENCE MATCH: how well the references fit this query (use the similarity
   scores and how alike the source waters are), and note that the query water quality is
   user-provided while the reference water quality is a database aggregate.
4. RISKS & UNCERTAINTIES: scaling/fouling, salinity variability, the provenance difference
   between the user-provided query values and the reference aggregates, and (for any value
   drawn from a ~10 km / 30-year aggregate) that it is not a single intake measurement.
5. DATA TO CONFIRM: the single most useful measurement to verify the recommendation.
```

## Ground Truth (held out — for evaluation only, NOT part of the prompt)

The query site (row 71, City of Benjamin RO WTP) is a real operating plant, so how it
actually treats its water is the ground-truth answer. These are the operational fields
withheld to keep the query blind. **Do not include this block in the prompt** — use it only
to score the model's `RECOMMENDED TREATMENT TRAIN`.

```text
GROUND TRUTH — City of Benjamin RO WTP (row 71), in operation since 2012
  Process:            brackish-water reverse osmosis (BWRO)
  Recovery:           71%
  Feed pressure:      165 psi
  Pre-treatment:      cartridge filter, oxidation, disinfection (chlorination/chloramination)
  Blending:           yes
  Post-treatment:     blending, pH adjustment, antiscalant, disinfection
  Concentrate:        evaporation pond
  Capacity:           ~0.07 MGD (small system)
```

This is the informative kind of test case: with **no references**, the model reasons from
first principles. Two points to check the output against the ground truth — (a) recovery is
a modest **71%**, lower than the 75–80% typical of the fresher brackish plants, which suits
this much saltier/harder feed; (b) concentrate goes to an **evaporation pond**, not the
deep-well injection common in Florida — a choice that fits an arid, inland, small system. A
model that blindly transfers "deep well injection, 80% recovery" from general RO knowledge
would miss both, which is exactly what the no-reference flag is meant to guard against.

## Notes

- Threshold `0.50` is a starting value (`similarity = 1/(1+distance)`, so 0.50 ≈ one standard
  deviation of average analyte difference); calibrate it in the retrieval layer.
- The instruction block is identical to the three-shot prompt; only the `REFERENCE PLANTS`
  block differs (the no-match message instead of R1–R3), so a single template serves both
  cases — the retrieval layer fills in whichever block applies.
- Numbers are rounded; the source CSV holds full precision. Query source-water stats use the
  30-year window; here they are a sparse 3-station aggregate, so treat them as indicative.

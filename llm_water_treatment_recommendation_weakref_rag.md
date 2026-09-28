# LLM Example — RAG Treatment Recommendation (A/B Test · Variant B: show weak references)

**A/B test, variant B.** Both variants use the same query (row 71, City of Benjamin RO WTP,
best RAG similarity 0.491 < 0.50 threshold). This variant, **B**, *shows* the nearest 1–2
sub-threshold matches, clearly labeled **LOW SIMILARITY — directional context only**, and
tells the model to reason from first principles and not over-anchor on them. Variant **A**
(`llm_water_treatment_recommendation_noreference_rag.md`) instead hides them (no references).
Score both outputs against the same held-out ground truth to see whether showing weak
references helps or misleads.

- **Retrieval:** `rag_sample_extraction/extract_rag_samples.py`.
- **Query:** `SOURCE EXCEL ROW = 71` — unusually saline, high-hardness inland brackish
  groundwater (near-site median TDS ~7,700 mg/L, sodium ~1,700, calcium ~700).
- **Weak references shown:** the top 2 matches, both below the 0.50 threshold —
  row 113 (similarity 0.491, but on only 4 shared analytes) and row 14 (0.389, on 10 shared
  analytes). Neither is a strong analog; they are shown for directional context only.

## Water-quality data provenance (important for the pilot)

- **Query site — user-provided.** Row 71's 30-year near-site aggregate stands in, and it
  rests on only **3 nearby stations**, so it is itself sparse and uncertain.
- **Reference plants — from our database** (30-year, ~10 km neighborhood aggregates). Here
  they are weak (sub-threshold) analogs, not trusted references.

## The Prompt

```text
You are a desalination and water-treatment analyst. Recommend HOW to treat the source water
at the query site to meet its stated purpose. Reference plants may be provided — real,
operating facilities retrieved as the most similar to the query by source-water chemistry,
water source, intended purpose, and process family. Do not output a fixed verdict; reason
from the evidence and say which reference(s) support each choice.

Reference quality — each reference has a similarity score in [0,1] (1 = identical) and a
"shared analytes" count showing how many features the comparison used:
- References at or above 0.50 are relevant analogs; weight higher scores more.
- References below 0.50 are marked LOW SIMILARITY. Use them ONLY for directional context —
  the query differs substantially, so reason primarily from first principles and adjust for
  the differences. Do not copy a weak reference's site-specific choices (e.g. concentrate
  disposal method, exact recovery) without checking they fit the query.
- A low "shared analytes" count means the similarity rests on little data and is unreliable.

Data provenance — the query site's water quality is user-provided (a direct intake/well
analysis of the actual feed); each reference's water quality is a 30-year, ~10 km
neighborhood aggregate from a database (median = typical, with a min–max envelope). Treat the
user's query values as the more direct measurement; use reference water quality mainly to
judge how alike each analog is, not as ground truth for the query.

════════════════════════════════════════════════════════════════════════
REFERENCE PLANTS — LOW SIMILARITY (both below the 0.50 threshold; directional context only)
════════════════════════════════════════════════════════════════════════
[R1] Englehard — Hyde County, NC        | similarity 0.491 | shared analytes: 4 (LOW — unreliable)
  Purpose: drinking water | Source: brackish groundwater | Raw TDS: ~623 mg/L
  Source water (30-yr near-site median [min–max]): salinity 8.5 [8.3–8.6] ppth; specific
    conductance 2,180 [265–2,510] µS/cm; pH 7.8; temp 27 °C  (TDS/major ions not reported)
  HOW IT IS TREATED:
    Process: brackish-water reverse osmosis (BWRO) | Pre-treatment: antiscalant | Blending: none
    Permeate TDS: ~25 mg/L | Post-treatment: acid, lime, phosphate, chlorine
    Concentrate: surface water discharge | Capacity: 0.43 MGD

[R2] Tarpon Springs RO Facility — Pinellas County, FL | similarity 0.389 | shared analytes: 10
  Purpose: drinking water | Source: brackish groundwater | Raw TDS: 11,520–12,800 mg/L
  Source water (30-yr near-site median [min–max]): TDS 2,670 [1.5–37,300] mg/L; salinity
    11.8 [0–46.4] ppth; sodium 795 [5–10,900]; calcium 107; magnesium 74; pH 8.0; temp 25.6 °C
  HOW IT IS TREATED:
    Process: brackish-water reverse osmosis (BWRO) | Recovery: 72% | Feed pressure: 350 psi
    (1st stage) / 450 psi (2nd stage) | Pre-treatment: acid, antiscalant, cartridge filters
    Blending: yes | Permeate: 297 µS/cm | Post-treatment: CO2 pH adjustment, lime + caustic
    (alkalinity/hardness), hypochlorite disinfection, fluoride | Concentrate: deep well injection

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
2. GROUNDING: for each major choice, say whether a reference [R1/R2] supports it or it rests
   on first-principles reasoning, and note where the query differs from the weak references.
3. CONFIDENCE & REFERENCE MATCH: state that the only available references are LOW SIMILARITY
   (0.491 / 0.389, one on just 4 shared analytes), so confidence is limited; note the query
   water quality is user-provided while the reference water quality is a database aggregate.
4. RISKS & UNCERTAINTIES: scaling/fouling (this feed is far harder/saltier than the weak
   references), salinity variability, the provenance difference, and that both references and
   the sparse query aggregate are ~10 km / 30-year summaries, not intake measurements.
5. DATA TO CONFIRM: the single most useful measurement to verify the recommendation.
```

## Ground Truth (held out — for evaluation only, NOT part of the prompt)

Same ground truth as variant A — the real treatment train of the query plant.

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

## What this A/B test is meant to reveal

The weak references create a concrete **anchoring hazard** that the ground truth exposes:

- **Concentrate disposal.** Both weak references discharge concentrate to surface water (R1)
  or deep-well injection (R2); the ground truth uses an **evaporation pond** (fitting an arid,
  inland, tiny system). If variant B's output copies R1/R2's disposal method, that is the
  anchoring failure — variant A (no references) should be less prone to it.
- **Recovery.** Ground truth recovery is **71%**; R2 (the saltier analog) runs 72%, so a weak
  reference could actually help here. Watch whether B lands closer to 71% than A.
- **Reliability signal.** R1 scores higher (0.491) than R2 (0.389) but on only 4 shared
  analytes; a good output should trust R2's fuller comparison more than R1's score — a test of
  whether the model reads the "shared analytes" cue.

Compare each variant's `RECOMMENDED TREATMENT TRAIN` to the ground truth on: process, recovery,
pre-treatment, **concentrate handling**, and post-treatment. The most informative signal is
whether showing weak references improves recovery/pretreatment estimates **without** dragging
the concentrate choice toward the (inapplicable) reference methods.

## Notes

- Threshold `0.50` and the LOW-SIMILARITY band are starting values; calibrate in the retrieval
  layer. A stricter floor (e.g. drop references below ~0.30) would exclude R2 here.
- The instruction and query/output blocks match variant A and the three-shot prompt; only the
  `REFERENCE PLANTS` block differs, so one template serves all cases.
- Numbers are rounded; the source CSV holds full precision.

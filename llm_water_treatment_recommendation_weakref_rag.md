# LLM Example — RAG Treatment Recommendation (A/B Test · Variant B: show weak references)

**Controlled A/B test, variant B.** All variants use the **same query as the three-shot
prompt** — row 26, North Cape Coral RO WTP — and the **same held-out ground truth**, so only
the *reference condition* changes:

- **Three-shot** (`llm_water_treatment_recommendation_threeshot_rag.md`): 3 **strong**
  references (row 26's real top matches, similarity 0.73–0.75).
- **Variant A** (`llm_water_treatment_recommendation_noreference_rag.md`): **no references**.
- **Variant B (this file): low-similarity references** — row 26's two most *dissimilar*
  same-class matches (similarity ~0.28–0.33), shown but labeled **LOW SIMILARITY — directional
  context only**.

Holding the query and ground truth fixed isolates the A-vs-B question: **does showing weak,
dissimilar references help or mislead, versus showing none?** (In production these weak
matches would fall below the 0.50 threshold; here they are supplied to row 26 on purpose to
create the weak-reference condition against the same ground truth.)

- **Weak references shown:** row 71 (similarity 0.28, on 10 shared analytes) and row 94
  (similarity 0.33, on 9 shared analytes). Both pass the same hard filters as the query
  (drinking water / groundwater / RO family) but are chemically far from it — one much
  saltier, one much fresher.

## Water-quality data provenance (important for the pilot)

- **Query site — user-provided.** Row 26's 30-year near-site aggregate stands in.
- **Reference plants — from our database** (30-year, ~10 km aggregates). Here they are weak
  (sub-threshold) analogs, not trusted references.

## The Prompt

```text
You are a desalination and water-treatment analyst. Recommend HOW to treat the source water
at the query site to meet its stated purpose. Reference plants may be provided — real,
operating facilities retrieved as the most similar to the query by source-water chemistry,
water source, intended purpose, and process family. Do not output a fixed verdict; reason
from the evidence and say which reference(s) support each choice.

Reference quality — each reference carries a similarity score in [0,1] (1 = identical) and a
"shared analytes" count showing how many features the comparison used:
- References at or above 0.50 are relevant analogs; weight higher scores more.
- References below 0.50 are marked LOW SIMILARITY. Use them ONLY for directional context —
  the query differs substantially, so reason primarily from first principles and adjust for
  the differences. Do not copy a weak reference's site-specific choices (e.g. concentrate
  disposal method, exact recovery) without checking they fit the query.
- A low "shared analytes" count means the similarity rests on little data and is unreliable.

Data provenance — the query site's water quality is user-provided (a direct intake/well
analysis of the actual feed); each reference's water quality is a 30-year, ~10 km neighborhood
aggregate from a database. Treat the user's query values as the more direct measurement; use
reference water quality mainly to judge how alike each analog is, not as ground truth.

════════════════════════════════════════════════════════════════════════
REFERENCE PLANTS — LOW SIMILARITY (both below the 0.50 threshold; directional context only)
════════════════════════════════════════════════════════════════════════
[R1] City of Benjamin RO WTP — Knox County, TX | similarity 0.28 | shared analytes: 10
  Purpose: drinking water | Source: brackish groundwater | Capacity: ~0.07 MGD
  Source water (30-yr near-site median [min–max]): TDS 7,680 [457–21,800] mg/L; specific
    conductance 11,200 [693–42,300] µS/cm; sodium 1,745 [25–8,233]; calcium 699; magnesium
    234; pH 7.9; temp 20.5 °C  — i.e. MUCH saltier/harder than the query
  HOW IT IS TREATED:
    Process: brackish-water reverse osmosis (BWRO) | Recovery: 71% | Feed pressure: 165 psi
    Pre-treatment: cartridge filter, oxidation, disinfection | Blending: yes
    Post-treatment: blending, pH adjustment, antiscalant, disinfection | Concentrate: evaporation pond

[R2] Glassboro — Gloucester County, NJ | similarity 0.33 | shared analytes: 9
  Purpose: drinking water | Source: brackish groundwater | Capacity: ~1.1 MGD
  Source water (30-yr near-site median [min–max]): TDS 96 [15–1,220] mg/L; specific
    conductance 178 [0–49,200] µS/cm; sodium 11; calcium 7; magnesium 3; pH 6.1; temp 17 °C
    — i.e. MUCH fresher than the query
  HOW IT IS TREATED:
    Process: reverse osmosis / vibratory shear enhanced processing | Feed pressure: ~200 psi
    Pre-treatment: 1 µm cartridge filters | Blending: yes
    Post-treatment: chlorine, orthophosphate | Concentrate: sewer discharge

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
2. GROUNDING: for each major choice, say whether a reference [R1/R2] supports it or it rests
   on first-principles reasoning, and note where the query differs from the weak references.
3. CONFIDENCE & REFERENCE MATCH: state that the only available references are LOW SIMILARITY
   (0.28 / 0.33), so confidence is limited; note the query water quality is user-provided
   while the reference water quality is a database aggregate.
4. RISKS & UNCERTAINTIES: scaling/fouling, salinity variability, the provenance difference,
   and that both references and the query aggregate are ~10 km / 30-year summaries, not
   intake measurements.
5. DATA TO CONFIRM: the single most useful measurement to verify the recommendation.
```

## Ground Truth (held out — for evaluation only, NOT part of the prompt)

Same ground truth across all variants — the real treatment train of the query plant.

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

The two weak references bracket the query (R1 far saltier, R2 far fresher) and disagree with
the ground truth on specifics — the anchoring hazard to watch:

- **Recovery.** Ground truth is **80%**; R1 runs 71%. If variant B drifts toward ~71% while
  variant A (no references) stays nearer 80%, the weak reference is misleading.
- **Concentrate disposal.** Ground truth (and the query's stated available option) is
  **deep well injection**; the weak references use an evaporation pond (R1) or sewer discharge
  (R2). A good output should keep deep well injection and NOT copy the references' methods.
- **Process.** Both references and the truth are BWRO, so process should be easy; R2's exotic
  "RO / vibratory shear" should not be transferred to a 12 MGD municipal plant.

Compare B against A and against the three-shot output on these axes. The headline question:
does supplying weak, dissimilar references improve the recommendation, leave it unchanged, or
drag it toward the references' ill-fitting choices?

## Notes

- Threshold `0.50` and the LOW-SIMILARITY band are starting values; calibrate in the retrieval
  layer. A stricter floor would exclude these references entirely (variant A).
- The instruction, query, and output blocks match variant A and the three-shot prompt; only
  the `REFERENCE PLANTS` block differs, so one template serves all cases.
- Numbers are rounded; the source CSV holds full precision.

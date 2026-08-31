# RAG Sample Extraction

Selects the most similar existing plants from the public dataset to use as **positive
few-shot examples** for a query plant's prompt. Every plant in the dataset is an
operating facility, so a retrieved neighbor is an implicit positive ("this water was
worth processing").

Selection is two stages: **hard filters first, then weighted similarity.**

## 1. Hard filters (must all pass)

A candidate is only comparable if it shares the query's:

| Filter | Column | Why |
|--------|--------|-----|
| `purpose` | `PURPOSE` | Different intended uses (drinking water vs. reuse) are regulated differently. |
| `source` | `WATER SOURCE` | Source type drives salinity / sodium / ion makeup. |
| `process` | `TYPE` | Process family behaves differently (RO ≠ NF ≠ …). |

Matching is on normalized values. `process` is grouped into a **family** so the many
`… / reverse osmosis` variants all count as `ro` (families: `ro`, `nf`, `ed`,
`membrane_filtration`, `other`). If the query's own value for a filter is unknown, that
filter is skipped. Disable filters with `--filters purpose,source` or `--filters none`.

## 2. Similarity (on the survivors)

We compare plants using the 30-year water-quality **analyte medians** (TDS, specific
conductance, salinity, conductivity, Ca, Mg, Na, K, pH, temperature, turbidity). Three
steps: put every analyte on a comparable scale, measure the gap, turn it into a score.

**Step A — put analytes on a comparable scale (standardize).**
Raw analytes are not comparable: TDS is in the hundreds–thousands while pH is ~7, so
without scaling TDS would dominate. Two fixes:

1. **Log-scale** the analytes that span orders of magnitude (TDS, conductance, salinity,
   the ions, turbidity), so "300 vs 3,000" counts like "3,000 vs 30,000" — a *ratio*
   difference, not an absolute one. pH (already logarithmic) and temperature stay as-is.
2. **Z-score** each analyte across all plants:  `z = (value − average) / spread`, where
   *average* and *spread* (standard deviation) are computed once over the whole dataset.
   After this, every analyte is centered at 0 with a spread of 1, so a "1-unit" difference
   means the same thing for TDS as for pH.

**Step B — measure the gap (distance).**
For two plants, take the difference of their z-scores on each analyte, square it, and
average (weighted) across the analytes they *both* have:

```
distance = sqrt(  sum over shared analytes of  weight × (z_query − z_candidate)²
                  ──────────────────────────────────────────────────────────── )
                              sum of those weights
```

This is a standard (Euclidean) distance, with two practical touches: it only uses analytes
present in **both** plants and divides by the weights actually used (a *Gower-style*
average), so a plant missing a few analytes still gets a fair, comparable score instead of
breaking. `distance = 0` means identical; larger means more different.

**Step C — turn distance into a similarity score.**
`similarity = 1 / (1 + distance)` — always between 0 and 1, where **1 = identical** and it
falls toward 0 as plants differ. Ranking by this is the same as ranking by distance; it
just gives a bounded, readable number.

**Weights** scale how much each analyte counts in Step B. They are **equal (all 1) for
now**. When the expert provides a sorted feature-importance list, convert it to per-analyte
weights and pass `--weights weights.json` (or a two-column `analyte,weight` CSV) — no code
change needed.

The **top-k** survivors by similarity are the selected positive samples. Optionally,
`--bottom-k` also returns the **least similar** survivors — same-class plants (they pass
the same hard filters) whose water chemistry is most different from the query. These are
useful as contrast/negative examples to offset the all-positive-label bias. The top and
bottom selections never overlap; the bottom is ranked most-dissimilar first.

## Usage

```bash
# One query plant (leave-one-out), top 5 similar samples
python rag_sample_extraction/extract_rag_samples.py --query-row 26 --top-k 5

# Also return the 3 most dissimilar same-class plants as contrast
python rag_sample_extraction/extract_rag_samples.py --query-row 26 --top-k 5 --bottom-k 3

# Every plant as a query -> combined table (initial experiment)
python rag_sample_extraction/extract_rag_samples.py --all-queries --top-k 5 --bottom-k 3

# Later: expert-weighted similarity
python rag_sample_extraction/extract_rag_samples.py --query-row 26 --weights weights.json

# Options: --filters purpose,source,process | none    (default all three)
#          --exclude-same-county   (drop query's own state+county; avoids shared-neighborhood leakage)
```

Input defaults to `Water_quality_data/outputs/water_quality_stats_30yr_per_plant.csv`
(one row per plant, built by `Water_quality_data/build_water_quality_stats_dataset.py`).

## Output

`outputs/rag_topk_query_<id>.csv` (single query) or `outputs/rag_topk_all_queries.csv`
(leave-one-out). One row per selected sample: `query_row`, `selection` (`top` = similar,
`bottom` = dissimilar), `rank`, `similarity`, `features_used`, the candidate's facility
fields, and its analyte medians.

## Initial-experiment notes

- Validation: for the target `row 26` (North Cape Coral RO), the top pick is `row 18`
  (City of Hialeah RO) — the same analog chosen by hand for the one-shot prompt example.
- With `--all-queries`, 60 of 86 plants get matches; the rest have no usable water-quality
  data, or no same-class candidate passes the hard filters (e.g. the lone seawater or
  electrodialysis plant). A query with `< top-k` survivors returns fewer samples.
- The similarity uses the **median** of each analyte's 30-year window. `max` values in the
  source data are far-well/seawater-intrusion outliers and are intentionally not used.

## Planned extensions (not yet implemented)

- Expert-weighted similarity (drop in `--weights`).
- Diversity among the k samples (MMR) instead of pure top-k.
- A boundary/contrast sample to offset the all-positive-label bias.
- Optionally add soil features to the similarity vector.

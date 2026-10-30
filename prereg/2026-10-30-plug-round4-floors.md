# Plug round 4, amendment 2 (2026-10-30): the RAG floor and the untrained 1B

Claim tags: [measured], [established], [hypothesis]. Written and committed BEFORE either floor has been run on the primary items. **The primary item set (251 recurrences in 89 repositories, 250 negatives) was already scored for the agree rule, the general-judge arm and the nightly arm; no floor outcome has been seen** [measured]. This note adds rows only; it changes no earlier design, rule, threshold or verdict.

## Floors
- **RAG floor** (similarity cutoff, no judge): the ranker's top lesson is answered when its similarity score reaches a cut, otherwise silence.
- **Untrained 1B:** the same pairwise prompt with no adapter, under the same agree rule (ranker cut plus the untrained P(yes) threshold).
- Both cuts are fitted on validation only (round 3's 40 scored repositories, nested repo-fold CV at wrong pick at most 0.05, the same fit as the other arms): RAG floor ranker score >= 16.0; untrained 1B ranker score >= 16.0 and P(yes) >= 0.76 [measured]. The file is `results/plug-r4-floors-selection.json`, pinned in `results/plug-r4-floors-pins.json`.

## Decision rules
Each floor is read against (a) the agree rule and (b) the round 3 judge alone at its frozen 0.99, on the primary metric (per-repo mean coverage, repo-clustered bootstrap, 10,000 resamples, seed 0, wrong pick over all 501 items). "Worse" means the interval of (floor minus comparator) has its upper bound below zero; "better" means the lower bound above zero and the gain at least 0.05; otherwise "tie" [established]. The sentence "training beats retrieval" may be used only if BOTH floors read "worse" than the agree rule AND the agree rule's wrong pick is at most 0.05; each floor's own wrong pick is printed, and a floor that exceeds 0.05 is reported as such, not tuned. Exact Clopper-Pearson bounds are printed beside the bootstrap bounds (a correction after scoring: the bootstrap is degenerate at zero).

## Cost
Inference only: the untrained scoring is one pass of 5,010 queries, about 2 GPU minutes (5 with margin) [hypothesis]; the RAG floor needs no model.

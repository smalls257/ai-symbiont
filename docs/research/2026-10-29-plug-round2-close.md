# Plug round 2, closed: V1 and V2 on the validation repos (2026-10-29)

Frozen under `prereg/2026-10-29-plug-sit-cuda.md` (freeze commit eb927ce). Validation only: round 2 stopped after V2, on the owner's decision, and is superseded by a pairwise-judge design (round 3). **No scored run happened under it.** These results are reported as measured, with no re-slicing.

All variants trained from plain weights on the 5080 desktop, with the CUDA backend run by the CUDA-port agent. Each ran from a clean checkout of eb927ce, with seeds 0 to 2 [measured: the desktop's recorded HEAD and status, and its script hashes, match the frozen tree]. Selection and scoring ran on the laptop with the frozen `plug_r2_select.py` (`results/plug-round2-validation.json`). Every number is a per-repo mean over the 10 validation repos and over the three seeds.

## Rows (validation; the shuffled top 5 of a 60-lesson prompt)

| Row | Pick | Silence | Wrong pick |
|---|---|---|---|
| plain 1B (floor) | 0.000 | 0.944 | 0.000 |
| V1: situation reader | 0.079 | 0.967 | 0.027 |
| V2: V1 plus 14 situation phrasings per lesson | 0.683 | 0.760 | 0.165 |
| ranker alone (top-1 note; the bar) | 0.735 | 0.000 | 0.620 |

All rows are [measured]. Per seed, V1 picks 0.025, 0.161 and 0.050, and V2 picks 0.681, 0.701 and 0.667 [measured].

## Selection, by the frozen rule

- **V1 against the floor.** Pick gain +0.079 [+0.033, +0.138], which reads `better`, and V1 passes the absolute abstention gate: silence 0.967 with a lower bound of 0.929, wrong pick 0.027. **V1 replaces the floor** [measured].
- **V2 against V1.** Pick gain +0.604 [+0.483, +0.733], which reads `better`, but silence falls by 0.207 (rule (b) allows 0.05) and wrong pick rises by 0.138 (rule (c) allows 0.02). **V2 does not replace V1** [measured]. The selected variant at the stop is V1.
- **Not run:** V3, V4 and the scored run.

## Reading

- **Rewordings were the lever for picking.** Fifteen phrasings per lesson lifted pick from 0.08 to 0.68, close to the ranker's first guess at 0.735 [measured].
- **They cost silence.** V2 states a fix on about a quarter of the situations where none applies [measured]. One generative reader trades picking against staying silent.
- **Why round 3.** Round 3 separates the two: a judge scores each shortlisted lesson, silence is a threshold on its top score, and the note is the stored lesson's text [hypothesis that this keeps V2-level picking without the confabulation cost].

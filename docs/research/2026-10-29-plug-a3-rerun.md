# Plug a3 rerun: consolidation on 10 repos (2026-10-29)

Exploratory; no prereg. Laptop MLX, Llama 3.2 1B Instruct. Results: `results/plug-a3-rerun.json` (pooled rows, verdicts and one row per repo and arm). Code: `scripts/routea/plug_a3.py` and `plug_a3.sh`, tests in `tests/scripts/test_plug.py`.

## Design

- **Repos.** Every pool repo with 8 or 9 distinct LCAP lessons: 10 repos [measured]. None is one of the 13 scored Plug repos, kept untouched for the frozen run, or one of the two feasibility repos. The 10-lesson budget needs 13 lessons (10 trained plus 3 new), and no repo outside the scored set has them [measured]. So this rerun uses one budget: 5 lessons trained, 3 held back as new lessons.
- **a2 variant (a2v).** The feasibility a2 saw these repos, so a2v was meta-trained without them and without the 13 scored repos. It has 61 meta-train repos and 1,373 rows [measured]; `plug.check_unseen` raises on any shared repo or lesson id.
- **Arms per repo.**
  - Per-repo adapter from plain 1B (reference): 8 epochs on the repo's rows.
  - a1: plain 1B, lessons in the prompt (reference).
  - a2v: lessons in the prompt only (reference).
  - a3: from a2v, the repo's rows plus twice as many prompt-reading rows, 8 epochs.
  - a3-more: the same mix for 16 epochs, so twice the exposure to the repo's rows.
  - a3-replay: a3 plus one AIDev habit row replayed for each of the repo's rows.
  - a3-more-replay (designed after the first a3 results were seen, so post hoc; queued after the scored run, owner GO): a3-replay's rows for 16 epochs. Its go rule adds a habits bar fixed before it ran: ranked habits at least a2v's minus 0.10.
- **Probes.** 25 reworded probes per repo for the trained lessons and 15 for the new lessons [measured]: 250 and 150 pooled. Wrong lessons come from the next repo by name.
- **Answers.** All answers come from one version of `scripts/routea/answer_questions.py`. The results file records its sha256. That record was written after the answers, from a script unchanged in git since before the run began.

## Results (means over the 10 repos, with a bootstrap interval by repo)

Intervals are 95% percentile bootstrap intervals over repos (10,000 resamples, seed 0) [established].

| Arm | (1) No lessons in prompt | (2) Lessons in prompt | (3) New lessons in prompt | (4) Habits: ranked / keyword | (5) Wrong lessons: recall / confabulation / abstention |
|---|---|---|---|---|---|
| Per-repo adapter (reference) | 0.56 [0.49, 0.63] | 0.52 | 0.43 [0.35, 0.52] | 0.23 / 0.38 | 0.38 / 0.04 / 0.00 |
| a1 (reference) | 0.01 | 0.37 [0.32, 0.41] | 0.45 [0.40, 0.51] | 0.20 / 0.50 | 0.02 / 0.05 / 0.00 |
| a2v (reference) | 0.00 | 0.58 [0.50, 0.66] | 0.71 [0.65, 0.75] | 0.95 / 0.64 | 0.00 / 0.00 / 1.00 |
| a3 | 0.62 [0.54, 0.72] | 0.54 | 0.67 [0.57, 0.77] | 0.24 / 0.25 | 0.00 / 0.00 / 1.00 |
| a3-more | 0.66 [0.56, 0.77] | 0.53 | 0.76 [0.68, 0.85] | 0.20 / 0.27 | 0.00 / 0.00 / 1.00 |
| a3-replay | 0.58 [0.52, 0.63] | 0.54 | 0.63 [0.57, 0.69] | 0.91 / 0.82 | 0.00 / 0.02 / 0.97 |
| a3-more-replay | 0.62 [0.55, 0.69] | 0.53 | 0.70 [0.62, 0.77] | 0.94 / 0.74 | 0.00 / 0.00 / 1.00 |

All rows are [measured]. Verdicts by the unchanged rule on the means (go: (1) at least the per-repo adapter's and (3) at least a2v's; kill: (3) below a1's):
- **a3-more: go** [measured]. 0.66 against 0.56 on (1); 0.76 against 0.71 on (3).
- **a3: hold** [measured]. 0.67 on (3) is just under a2v's 0.71.
- **a3-replay: hold** [measured]. 0.63 on (3) is under a2v's 0.71; it keeps the habits (0.91 ranked), as a3-more-replay does (0.94).
- **a3-more-replay: hold** [measured]. It passes (1) (0.62 against 0.56) and the habits bar (0.94 against 0.95 − 0.10), and misses (3) by 0.007 (0.700 against 0.707).
- No arm is killed [measured].

## Paired by repo (arm minus reference, bootstrap interval over repos)

| Arm | (1) minus per-repo adapter | (3) minus a2v | Ranked habits minus a2v |
|---|---|---|---|
| a3 | +0.06 [+0.00, +0.13] | −0.04 [−0.12, +0.03] | −0.72 [−0.77, −0.67] |
| a3-more | +0.10 [+0.03, +0.18] | +0.05 [−0.02, +0.12] | −0.75 [−0.81, −0.70] |
| a3-replay | +0.02 [−0.04, +0.08] | −0.07 [−0.14, −0.01] | −0.04 [−0.11, +0.02] |
| a3-more-replay | +0.06 [−0.01, +0.12] | −0.01 [−0.09, +0.06] | −0.01 [−0.07, +0.03] |

All rows are [measured]. a3-more's lead on (1) is resolved: its interval is above 0. Its lead on (3) is not. a3-more-replay's habits sit at a2v's [measured].

## Reading

- The verdicts compare means. The intervals of (1) for a3-more and the per-repo adapter overlap, and so do those of (3) for a3-more and a2v [measured]. "Go" means the means pass the rule, not that the gap is resolved.
- Consolidating without replay wipes the habits: a3 and a3-more fall to chance on ranked choice (0.24 and 0.20). Replaying habit rows keeps them (0.91) at a small cost in new-lesson recall [measured].
- Every arm meta-trained to read its prompt abstains when another repo's lessons stand in (abstention 0.97 to 1.00, confabulation at most 0.02) [measured]. The per-repo adapter and a1 confabulate 0.04 to 0.05 and never abstain [measured]. The per-repo adapter still answers from its weights under wrong lessons (0.38 recall).
- a2v alone already reads its prompt best of the no-training arms (0.58 trained, 0.71 new) and keeps habits (0.95) [measured]. That is the arm the frozen Plug run (`prereg/2026-10-29-l2l-a2.md`) scored on 13 unseen repos.
- One seed per arm and 10 small repos [hypothesis that seed spread is smaller than repo spread]. a3-more-replay is the combined arm: it keeps the habits and about half of a3-more's lead on (1) (+0.06 against +0.10 over the per-repo adapter).

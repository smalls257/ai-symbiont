# Plug a2-distract: training the reader with distractor lessons (2026-10-29)

Exploratory; no prereg. Laptop MLX, Llama 3.2 1B Instruct, on the a3 rerun's 10 repos and split (`docs/research/2026-10-29-plug-a3-rerun.md`). Results: `results/plug-distract.json`. Code: `scripts/routea/plug_distract.py` and `plug_distract.sh`, tests in `tests/scripts/test_plug.py`.

## Design

- **a2-distract (a2d)** is meta-trained once from plain 1B on the same 61 meta repos as a2v. Each training prompt holds 3 lessons, as a2v's do: 1 of the repo's own and 2 from another meta-train repo. The answer comes from the right lesson [measured: 1,385 rows, plus the 202 AIDev habit rows]. Four lessons per prompt overflowed the 512-token window, so 197 rows over 1,300 characters were dropped [measured]. As in a2v, each lesson also gets an abstain row whose prompt holds only the other repo's lessons.
- **New measure, mixed prompt.** The repo's 5 lessons and the paired repo's 5 lessons are shuffled together. It is answered by a2d, a2v and a1 on the same 25 reworded probes per repo.

## Results (means over the 10 repos, bootstrap interval by repo)

Intervals are 95% percentile bootstrap intervals over repos (10,000 resamples, seed 0) [established].

| Arm | Own lessons | Mixed prompt | Mixed: confabulation / false abstention | New lessons | Habits (ranked) | Wrong lessons only: abstention |
|---|---|---|---|---|---|---|
| a1: plain 1B (reference) | 0.37 | 0.36 [0.32, 0.39] | 0.05 / 0.00 | 0.45 | 0.20 | 0.00 |
| a2v (reference) | 0.58 | 0.61 [0.54, 0.68] | 0.00 / 0.04 | 0.71 | 0.95 | 1.00 |
| a2d (under test) | 0.42 | 0.25 [0.20, 0.30] | 0.00 / 0.13 | 0.55 | 0.82 | 1.00 |

All rows are [measured].

## Reading

- a2d is worse than a2v on every recall measure, and on mixed prompts it is worse than plain 1B (0.25 against 0.36) [measured].
- a2v already handles a mixed prompt: 0.61 recall, no confabulation [measured]. On these probes there was no distractor problem left for the extra training to fix.
- False abstention explains only part of the drop: 0.13 on mixed prompts for a2d against 0.04 for a2v [measured].
- One plausible cause: a2d's training prompts hold only 1 applicable lesson in 3, so it trains on fewer applicable rows per prompt [hypothesis].
- **Verdict: this recipe is not carried forward.** The situation test (round 2) is the harder distractor test: 60 lessons, mostly irrelevant. The pilot there decides which reader goes into the next prereg.

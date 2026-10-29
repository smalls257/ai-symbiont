# Plug a2, scored: a meta-trained reader on 13 unseen repos (2026-10-29)

Scored under `prereg/2026-10-29-l2l-a2.md` (amendment 1 adds row keys only). Run once at the freeze commit 24881aa: `plug.py check` recorded it as `code_commit` and passed the input hashes [measured]. Laptop MLX, Llama 3.2 1B Instruct. Results: `results/l2l-a2.json`, which also records the prereg's sha256, the answer script's sha256 and the a2 adapter's sha256.

## Verdict

**"A meta-trained reader did not measurably beat the plain model at this size"**: the sentence the run built from the decisions [measured]. Plug-and-play is not claimed.

Intervals are 95% percentile bootstrap intervals over the 13 repos (10,000 resamples, seed 0) [established].

| Decision | Words | Mean gain, with interval |
|---|---|---|
| H1: a2 minus a1, reworded recall, 5 lessons (primary) | tie | +0.06 [−0.01, +0.13] |
| a2 minus a1, 10 lessons (secondary) | tie | +0.03 [+0.01, +0.06] |
| a2 minus per-repo adapter, 5 lessons (secondary) | worse | −0.22 [−0.31, −0.12] |
| a2 minus per-repo adapter, 10 lessons (secondary) | worse | −0.20 [−0.27, −0.13] |
| Confabulation control, 5 lessons | passes | a2 rate 0.00 [0.00, 0.00]; a1 minus a2: better |
| Confabulation control, 10 lessons (secondary) | passes | a2 rate 0.00 [0.00, 0.00]; a1 minus a2 +0.10 [+0.03, +0.19]: better |
| Sensitivity: H1 without the 5 shared-key lessons (never decides) | tie | +0.06 [−0.01, +0.13] |

All rows are [measured]. At 10 lessons the interval is above 0 but the mean gain is under the 0.05 floor, so the rule reads tie.

## Rows (means over 13 repos, 5 lessons)

| Row | Label | Reworded recall | Verbatim | Abstention | Confabulation |
|---|---|---|---|---|---|
| plain 1B, no lessons | floor | 0.003 | 0.02 | 0.00 | n/a |
| a2, no lessons | floor | 0.00 | 0.00 | 1.00 | n/a |
| a1: plain 1B, lessons in the prompt | reference | 0.34 | 0.29 | 0.00 | n/a |
| per-repo adapter from plain 1B | reference | 0.62 | 0.78 | 0.00 | n/a |
| a2: meta-trained, lessons in the prompt | under test | 0.40 | 0.77 | 0.13 | n/a |
| a2 with the wrong repo's lessons | control | 0.00 | 0.00 | 1.00 | 0.00 |
| a1 with the wrong repo's lessons | control | 0.03 | 0.04 | 0.00 | 0.06 |

## Rows (means over 13 repos, 10 lessons)

| Row | Label | Reworded recall | Verbatim | Abstention | Confabulation |
|---|---|---|---|---|---|
| plain 1B, no lessons | floor | 0.008 | 0.01 | 0.00 | n/a |
| a2, no lessons | floor | 0.00 | 0.00 | 1.00 | n/a |
| a1: plain 1B, lessons in the prompt | reference | 0.34 | 0.30 | 0.00 | n/a |
| per-repo adapter from plain 1B | reference | 0.58 | 0.75 | 0.00 | n/a |
| a2: meta-trained, lessons in the prompt | under test | 0.37 | 0.71 | 0.16 | n/a |
| a2 with the wrong repo's lessons | control | 0.00 | 0.00 | 1.00 | 0.00 |
| a1 with the wrong repo's lessons | control | 0.05 | 0.06 | 0.00 | 0.10 |

All rows in both tables are [measured]. The plain-1B floor (0.003 at 5 lessons, 0.008 at 10) is above 0 but negligible: no probe gives its answer away in any useful measure [measured]. Habits kept by ranked choice: plain 1B 0.20, a2 0.80, the per-repo adapters 0.23 on average [measured].

## Reading

- On the primary measure a2 recalls 0.40 of the reworded probes against 0.34 for the plain model: a tie by the rule [measured]. The prereg's expectation of about a third of the feasibility gap (+0.11) lies inside the interval [−0.01, +0.13], so it is neither confirmed nor ruled out [measured].

The findings below are secondary and exploratory; none of them decides:
- Secondary: on the training wordings a2 is close to a per-repo adapter (0.77 against 0.78), with no training for the repo. It does not carry that over to the unseen rewordings (0.40 against 0.62) [measured].
- Secondary: under the prereg's confabulation scorer a2 never states another repo's fix as this one's: confabulation 0.00, abstaining on every wrong-lesson probe. The plain model confabulates on 0.06 of them [measured]. The cost is 0.13 false abstention on its own repo's probes [measured].
- Secondary (exploratory habits check): a2 keeps the AIDev habits (0.80 ranked against 0.20) [measured].
- One seed per arm and 13 repos, so seed variance is not estimated [hypothesis that it is smaller than the repo spread].

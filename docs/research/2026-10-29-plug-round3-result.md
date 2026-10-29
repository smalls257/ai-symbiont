# Plug round 3 result: the pairwise judge on 40 unseen repos (PLUG-JUDGE)

Prereg: `prereg/2026-10-29-plug-judge.md` (frozen at f5c362b), amendment 1 `prereg/2026-10-29-plug-judge-amendment-1.md` (validation fit). Results: `results/plug-judge.json`, written by `scripts/routea/plug_r3_score.py` exactly as frozen. Every row is labeled floor, reference or under test, and the plain rows print beside the judge.

## The claim sentence (built in code)

> the judge beat the thresholded ranker but failed the safety and habits gate; the judge's pick, precision, wrong pick 0.31, 0.72, 0.05 (ranker alone 0.76, 0.38, 0.62)

The sentence is the frozen code's, word for word. Its "0.05" is 0.0531 rounded [measured]; the safety gate failed on it (below). It says "gate" where two gates failed.

## Rows (40 scored repos, 330 items; per-repo means, precision pooled)

| Row | Label | Pick | Silence | Wrong pick | Precision | Coverage |
|---|---|---|---|---|---|---|
| judge, 1B, 3-seed mean P(yes) at 0.99 | under test | 0.310 | 0.931 | 0.053 | 0.722 | 0.348 |
| ranker with its threshold (IDF 15.0) | reference | 0.166 | 0.885 | 0.065 | 0.596 | 0.180 |
| ranker alone, always answering | reference | 0.764 | 0.000 | 0.618 | 0.382 | 1.000 |
| untrained 1B as judge at 0.91 | floor | 0.017 | 0.975 | 0.022 | 0.300 | 0.035 |
| plain 1B reading the top 5 | floor | 0.000 | 1.000 | 0.000 | none (never answered) | 0.000 |

All rows are [measured].

## Hypotheses

- **H1 (primary): `better`.** Judge minus thresholded ranker, per-repo pick: +0.145, 95% interval +0.058 to +0.239 over 40 repos [measured]. Amendment 1 had flagged H1 as underpowered (MDE 0.168); the gain still cleared the rule [measured].
- **H2 (safety gate): fails.** Silence 0.931, interval 0.867 to 0.983, passes its part. Wrong pick 0.053 with upper bound 0.103 fails both the 0.05 point limit and the 0.10 bound, narrowly [measured]. This was the first transfer test of a threshold fitted on validation (0.024 wrong pick there) [measured].
- **H3 (habits gate): fails.** Ranked habits 0.795 on the seed mean, Wilson interval 0.655 to 0.889 over 44 questions, against the 0.90 bar; the untrained 1B scores 0.227 [measured]. Habit rows were 2.1% of the mix, a risk the prereg named [measured].
- **H4 (new-lesson gate): passes.** Pick on new (scored) lessons minus pick on seen (meta-train) lessons under an unseen wording: +0.065, interval -0.058 to +0.186 [measured]. Lessons added after training did no worse than trained ones in a new wording.

Because H2 and H3 failed, the frozen rule withholds the full claim: no sentence here says the judge is safe to deploy.

## Secondary, never deciding

- **Against the ranker alone:** the judge picks 0.453 less (interval -0.543 to -0.359) and is 0.478 more precise (interval 0.386 to 0.558, over the 27 repos where it answered) [measured].
- **New failure keys:** on the 160 scored lessons whose key never occurs in meta-train (320 items), pick 0.325, wrong pick 0.063, precision 0.722 [measured].
- **Wrong picks of trained lessons:** none of the judge's 20 wrong picks chose a meta-train lesson [measured].
- **Per seed, each at its own validation threshold:** seed 0 (0.991) silence 0.931, wrong pick 0.056, fails H2; seed 1 (0.99) 0.935 and 0.049, passes; seed 2 (0.99) 0.944 and 0.043, passes [measured]. The ensemble fails where two of three seeds pass.

## Provenance and disclosures

- Trained and scored on the 5080 from the freeze commit with a clean tree; script hashes equal the frozen ones; the scored outputs match `logs/SHA256SUMS-scored` [measured].
- Seed 2 was retrained once after a desktop disk failure (the first attempt died before saving) with the same frozen code [measured].
- The trainer's per-step loss lines went to stdout and were not kept beyond the final lines, because `plug_r3.sh` logged stderr only [measured].
- Situations are built from each lesson's own record, which flatters the lexical ranker and the judge alike.
- No sentence of this result implies agent success; that is PLUG-AGENT-1 and PLUG-AGENT-2.

## Reading

The judge nearly doubles the thresholded ranker's pick (0.310 against 0.166) at similar silence, but it misses the wrong-pick limit by about 0.003 and forgets habits [measured]. The likely levers are a larger habit share and calibration of P(yes), which the validation fit pushed to 0.99 [hypothesis]. Any change needs a new prereg; this round is closed as reported.

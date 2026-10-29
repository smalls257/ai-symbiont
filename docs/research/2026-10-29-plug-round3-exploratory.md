# Plug round 3, exploratory: a pairwise judge over the ranker's shortlist (2026-10-29)

Exploratory, validation repos only, no prereg. The judges and V2's confidences ran on the 5080 desktop (CUDA), executed by the CUDA-port agent from clean checkouts of the code commits (99f0b65 and 15073e4 [measured: the desktop's HEAD, status and script hashes]). Thresholds and curves ran on the laptop. Results: `results/plug-r3-exploratory.json` (`plug_judge_cli.py combine`). Code: `scripts/routea/plug_judge.py`, `plug_judge_cli.py`, `plug_v2conf.py`, `score_pairs_torch.py`, `score_notes_torch.py`.

## Design

- **Ranker shortlist.** The ranker's top 10 hold the applicable lesson for every validation situation; the top 5 hold it for 0.976 [measured].
- **Judge.** Trained from plain weights, 3 epochs, seeds 0 to 2, on 618 balanced rows from meta-train lessons only: 309 "applies" and 309 hard negatives, the ranker's high-ranked wrong lessons. It answers yes or no for each shortlisted (situation, lesson). The note is the top-scoring lesson's stored text. Under a threshold on that top score the judge stays silent. Scores are means over the three seeds.
- **V2 with a threshold.** Round 2's V2 reader, silent when its mean log-probability of the stored note of the lesson it names is under a threshold.
- **Thresholds.** Fitted on the 5 validation repos lowest by name hash (82 items), to the safety limits: silence at least 0.80 and wrong pick at most 0.05. Each arm is reported on the other 5 repos (84 items).
- **Threshold grids.** The first grids (P(yes) in 0.05 steps; V2 log-probability in 0.1 steps from −4) jumped past every safe point. They were refined after that was seen, to 0.01 steps plus 0.991 to 0.999, and V2 to −1 to 0 in 0.01 steps, so the refinement is post hoc [measured].

## Results

| Arm | Fitted threshold | Held-out pick | Precision | Coverage | Silence | Wrong pick | Best pick within the safety limits, all 10 repos |
|---|---|---|---|---|---|---|---|
| Judge, 1B | P(yes) 0.91 | 0.786 | 0.767 | 0.881 | 0.857 | 0.119 | 0.470 at 0.93 |
| Judge, 3B | P(yes) 0.94 | 0.595 | 0.758 | 0.667 | 0.881 | 0.095 | 0.181 at 0.95 |
| Untrained 1B as judge | P(yes) 0.91 | 0.000 | n/a | 0.000 | 1.000 | 0.000 | 0.000 |
| Untrained 3B as judge | P(yes) 0.68 | 0.024 | 0.111 | 0.119 | 0.905 | 0.095 | 0.000 |
| V2 with a threshold | none safe below 0 | 0.000 | n/a | 0.000 | 1.000 | 0.000 | 0.000 |
| Ranker alone (always answers) | none | 0.810 | 0.405 | 1.000 | 0.000 | 0.595 | never safe |
| Plain 1B (round 2's floor) | none | 0.000 | n/a | 0.000 | 1.000 | 0.000 | 0.000 |

All rows are [measured]. Held-out columns are on 84 items. Judge training took 48 to 50 s per seed at 5.3 GB for 1B, and about 100 s at 12.5 GB for 3B [measured, desktop].

## Reading

- **The 1B judge is the first reader that picks well and can be made silent.** At its fitted threshold it picks 0.79 of held-out situations with precision 0.77 [measured]. The ranker alone picks 0.81 but can never be silent [measured].
- **The threshold does not transfer cleanly.** Fitted on 5 repos, it gives wrong pick 0.119 on the other 5, over the 0.05 limit [measured]. Across all 10 repos, the best point within the safety limits picks 0.47 [measured]. More fitting situations, or a different calibration, are needed [hypothesis].
- **V2's own confidence cannot be made safe.** Its log-probability for every note it names is near 0, so thresholding separates nothing [measured]. It is therefore not a baseline the judge must beat; the ranker alone and plain 1B are.
- **3B is worse than 1B as a judge here** [measured, one round, three seeds].

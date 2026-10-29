# Amendment 1 to PLUG-JUDGE (`prereg/2026-10-29-plug-judge.md`): validation fit

Dated 2026-10-29. Committed before any scored answer exists, as the frozen decision procedure requires. It records the numbers the validation fit produced and changes nothing in the frozen design.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or by construction, [hypothesis] = a guess the run can support or refute.

## Provenance

- Trained and scored on the 5080 from the freeze commit f5c362b with a clean tree; the desktop's script hashes for `plug_r3.sh`, `train_lora_torch.py` and `score_pairs_torch.py` equal the frozen ones [measured].
- The training log's first line reads `iters 7104 rows 9472`, as the prereg fixes [measured].
- Seed 2 was retrained once after a desktop disk failure: the earlier attempt died with a bus error at the final step, before saving an adapter. The retrain used the same frozen code [measured].
- `plug_r3.sh` logs the trainer's stderr only, so the per-step training losses were not kept; the adapters' checksums are in the bundle's `logs/SHA256SUMS-validation` [measured]. Seed training took 640 to 694 s [measured].
- Selection file: `selection.json` from `plug_r3_run.py fit` on the 3 seed files and the untrained file, 1,660 queries each [measured].

## Fitted thresholds (all 10 validation repos, 166 items)

| Row | Threshold | Pick | Silence | Wrong pick | Precision |
|---|---|---|---|---|---|
| judge, 3-seed mean P(yes) | 0.99 | 0.337 | 0.964 | 0.024 | 0.875 |
| thresholded ranker, top IDF score | 15.0 | 0.157 | 0.928 | 0.042 | 0.650 |
| untrained 1B as judge | 0.91 | 0.000 | 0.976 | 0.018 | 0.000 |

All rows are [measured]. Per-seed judge thresholds: seed 0 at 0.991, seeds 1 and 2 at 0.99 [measured]. Every row has a safe point, so H1 has a comparator and the untrained floor enters the scored run.

## Ranker grid coverage

Validation top IDF scores run from 2.71 to 19.92, inside the frozen grid of 0 to 30 [measured].

## Minimum detectable effect

Judge minus thresholded ranker on validation: mean per-repo gain 0.178, s 0.268 on the fitting repos, scaled to 0.380 for the scored repos, MDE 0.168 [measured]. The MDE exceeds 0.10, so **H1 is underpowered** before any scored answer; s is in-sample, so even 0.168 is optimistic. The round runs as preregistered.

## What looks off, stated before the scored run

- The judge's lowest safe threshold is 0.99, near the top of its grid, and its validation pick (0.337) is below the exploratory judge's best safe point (0.47 at 0.93) [measured]. The new mix appears to push P(yes) toward 1 for many wrong pairs, so only the grid's top points separate them [hypothesis]. The frozen grid and rule stand.

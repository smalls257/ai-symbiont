# Plug round 4 result (scored once, 2026-10-30)

Claim tags: [measured], [established], [hypothesis]. Scored on 251 real later recurrences in 89 repositories plus 250 negative items (501 items), under the frozen prereg (`prereg/2026-10-29-plug-round4-DRAFT.md`, frozen at a8f428c) and its amendments. Wording: small trained judge + ranker agreement.

## Bounds
The pre-registered repo-clustered bootstrap is degenerate at zero (all-zero data resamples to zero). Beside it we report the exact Clopper-Pearson 95% upper bound over items, a correction made after scoring; items are treated as independent, so repository clustering would widen it. No verdict changes (`results/plug-r4-bounds.json`) [measured].

| Arm | Wrong picks | Exact upper bound | Pre-registered bootstrap bound |
|---|---|---|---|
| Agree rule (primary) | 0 of 501 wrong | 0.73% | 0% (degenerate at zero) | [measured]
| Round 3 judge alone | 0 of 501 wrong | 0.73% | n/a | [measured]
| General-judge arm | 5 of 501 wrong | 2.3% | 2.7% | [measured]
| Nightly arm | 15 of 501 wrong | 4.9% | 5.65% | [measured]

## Results
- **Primary:** the agree rule covers 0.256 against 0.128 for the judge alone (gain 0.129, interval [0.033, 0.230]), reading better; 0 of 501 wrong (upper bound 0.73%). [measured]
- **General-judge arm:** 0.183 against 0.128, interval [-0.041, 0.149], tie.
- **Nightly arm:** +0.14 coverage [0.04, 0.24] over the fair reference, 87% precision, upper bound just over the pre-set 5% bar by the pre-registered bootstrap (5.65%; the exact bound is 4.9%); no claim, per the pre-registered rule. [measured]
- **Floors (RAG similarity cutoff, untrained 1B):** pre-registered in `prereg/2026-10-30-plug-round4-floors.md` before running; results pending at the time of writing.
- **Reptile:** exploratory and dropped. On validation the meta-trained start was worse than plain nightly training (pick 0.30, habits 0.58 at full strength) (`results/plug-r4-reptile.json`) [measured].
- **Winner's curse:** about 17 recipes were tried on validation; only this one scored run counts.

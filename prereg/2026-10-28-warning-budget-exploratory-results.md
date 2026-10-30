# Results of the exploratory warning-budget analysis (Task 14c)

**EXPLORATORY / POST-HOC.** Dated results file for
`prereg/2026-10-28-warning-budget-exploratory.md`, which stays exactly as
frozen at commit 1e64143 (its "Results" placeholder is superseded by this
file). It cannot change the frozen G6 outcome. Claim tags as in the frozen file.

## Results, 2026-10-27 (written after the run)

Run on the CPU host from code commit 7dc8116 (the analysis was frozen at
commit 1e64143, before any test-split budget metric); counts, ids and labels are in `results/warning-budget-exploratory.json`.
Test split: 82 tasks [measured], base rate of a pain point within 5 steps
0.152 [measured]. EXPLORATORY / POST-HOC; the G6 verdict is
unchanged. Intervals are 95% task-level bootstrap, 2,000 draws [measured].

### Table

| budget | row | role | precision | recall | flag rate on test | net benefit/100 steps c=0.5 | c=1 | c=2 | tag |
|---|---|---|---|---|---|---|---|---|---|
| none (floor) | warn on every step | floor | 0.152 [0.141, 0.163] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | -27.18 [-28.80, -25.59] | -69.57 [-71.73, -67.45] | -154.36 [-157.60, -151.18] | [measured] |
| 0.1 | counters | reference | 0.172 [0.157, 0.187] | 0.202 [0.184, 0.219] | 0.178 [0.165, 0.191] | -4.31 [-4.78, -3.87] | -11.70 [-12.62, -10.82] | -26.47 [-28.39, -24.58] | [measured] |
| 0.1 | fly | under test | 0.230 [0.200, 0.258] | 0.132 [0.097, 0.164] | 0.087 [0.065, 0.109] | -1.36 [-1.81, -0.94] | -4.73 [-5.87, -3.61] | -11.47 [-14.17, -8.73] | [measured] |
| 0.1 | fly seed 0 | under test | 0.229 [0.199, 0.257] | 0.131 [0.096, 0.164] | 0.087 [0.065, 0.109] | -1.37 [-1.83, -0.96] | -4.74 [-5.87, -3.61] | -11.47 [-14.15, -8.73] | [measured] |
| 0.1 | fly seed 1 | under test | 0.230 [0.200, 0.259] | 0.132 [0.097, 0.164] | 0.087 [0.065, 0.109] | -1.35 [-1.80, -0.93] | -4.71 [-5.85, -3.60] | -11.43 [-14.16, -8.69] | [measured] |
| 0.1 | fly seed 2 | under test | 0.230 [0.200, 0.258] | 0.132 [0.097, 0.165] | 0.088 [0.065, 0.109] | -1.36 [-1.83, -0.94] | -4.74 [-5.90, -3.62] | -11.50 [-14.20, -8.72] | [measured] |
| 0.15 | counters | reference | 0.171 [0.157, 0.184] | 0.257 [0.241, 0.272] | 0.229 [0.216, 0.241] | -5.59 [-6.03, -5.11] | -15.08 [-15.96, -14.18] | -34.07 [-35.87, -32.17] | [measured] |
| 0.15 | fly | under test | 0.231 [0.205, 0.254] | 0.203 [0.161, 0.243] | 0.134 [0.107, 0.160] | -2.05 [-2.58, -1.53] | -7.19 [-8.56, -5.81] | -17.47 [-20.77, -14.12] | [measured] |
| 0.15 | fly seed 0 | under test | 0.232 [0.206, 0.255] | 0.204 [0.162, 0.245] | 0.134 [0.107, 0.161] | -2.04 [-2.58, -1.53] | -7.20 [-8.54, -5.82] | -17.50 [-20.81, -14.14] | [measured] |
| 0.15 | fly seed 1 | under test | 0.230 [0.204, 0.253] | 0.202 [0.160, 0.242] | 0.134 [0.107, 0.160] | -2.07 [-2.60, -1.55] | -7.21 [-8.59, -5.83] | -17.49 [-20.77, -14.15] | [measured] |
| 0.15 | fly seed 2 | under test | 0.231 [0.205, 0.255] | 0.203 [0.160, 0.244] | 0.133 [0.106, 0.160] | -2.04 [-2.57, -1.52] | -7.17 [-8.52, -5.78] | -17.42 [-20.76, -14.08] | [measured] |
| 0.2 | counters | reference | 0.173 [0.160, 0.186] | 0.286 [0.271, 0.301] | 0.252 [0.239, 0.264] | -6.05 [-6.54, -5.55] | -16.45 [-17.34, -15.54] | -37.26 [-39.12, -35.40] | [measured] |
| 0.2 | fly | under test | 0.230 [0.208, 0.252] | 0.280 [0.231, 0.325] | 0.185 [0.153, 0.216] | -2.85 [-3.41, -2.29] | -9.96 [-11.45, -8.47] | -24.18 [-27.86, -20.43] | [measured] |
| 0.2 | fly seed 0 | under test | 0.232 [0.209, 0.253] | 0.283 [0.234, 0.328] | 0.185 [0.153, 0.217] | -2.82 [-3.38, -2.27] | -9.95 [-11.46, -8.47] | -24.20 [-27.88, -20.44] | [measured] |
| 0.2 | fly seed 1 | under test | 0.230 [0.207, 0.251] | 0.279 [0.231, 0.325] | 0.185 [0.153, 0.216] | -2.87 [-3.44, -2.32] | -10.00 [-11.49, -8.51] | -24.25 [-27.97, -20.52] | [measured] |
| 0.2 | fly seed 2 | under test | 0.230 [0.207, 0.252] | 0.277 [0.229, 0.323] | 0.184 [0.152, 0.215] | -2.85 [-3.41, -2.28] | -9.93 [-11.41, -8.43] | -24.08 [-27.75, -20.32] | [measured] |

| budget | difference | precision | recall | flag rate | net benefit/100 steps c=0.5 | c=1 | c=2 | tag |
|---|---|---|---|---|---|---|---|---|
| 0.1 | fly minus counters | 0.058 [0.033, 0.081] | -0.070 [-0.105, -0.038] | -0.091 [-0.115, -0.069] | 2.95 [2.37, 3.56] | 6.97 [5.54, 8.51] | 15.00 [11.71, 18.43] | [measured] |
| 0.15 | fly minus counters | 0.060 [0.041, 0.079] | -0.054 [-0.096, -0.014] | -0.095 [-0.123, -0.070] | 3.54 [2.91, 4.19] | 7.89 [6.28, 9.58] | 16.60 [12.89, 20.52] | [measured] |
| 0.2 | fly minus counters | 0.057 [0.041, 0.073] | -0.007 [-0.057, 0.039] | -0.067 [-0.099, -0.035] | 3.20 [2.47, 3.90] | 6.49 [4.57, 8.42] | 13.08 [8.72, 17.49] | [measured] |

Similarity: no flags (recall only); recall@3 0.087 [measured], as in G6.

### What the table says, and what it does not

- Every learner is below zero net benefit at every budget and every cost
  tried. A warning pays only when precision exceeds c / (1 + c), which is 0.33,
  0.50 and 0.67 for c = 0.5, 1 and 2 [established, arithmetic], and the best
  precision seen is about 0.23 [measured]. Staying silent (net benefit 0) beats
  every row on these steps. This is about these recorded steps and these assumed
  costs, not a verdict on live use.
- At the same nominal budget the fly has higher precision than the counters
  (about +0.06, intervals above zero at all three budgets) and a higher net
  benefit, but lower recall at budgets 0.10 and 0.15 [measured].
- The TRAIN threshold does not transfer exactly. At budget 0.10 the counters flag
  0.178 [0.165, 0.191] of test steps and the fly 0.087 [0.065, 0.109] [measured].
  The counters risk is a raw count of matching earlier events, which grows as
  history grows, so a threshold fixed on the shorter train replay over-flags
  later; the fly's weights relax, so its risk falls [hypothesis]. Compare the
  flag-rate column before the precision column: part of the net-benefit gap is
  that the counters spend more warnings than the budget and the fly fewer.
- The three wiring seeds agree to within about 0.002 in precision [measured].
- Nothing here changes the live-learner rule or the G6 result. Confirmatory use
  needs the Act 2 prereg to freeze the budget, precision at the budget and net
  benefit first (see `prereg/AGENTS.md`).

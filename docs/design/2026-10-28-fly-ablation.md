# Why the fly and DenseNet trail a batch classifier (T47, exploratory)

Status: exploratory, inside the 100-repository pool only (`results/repo-pool.json`). Pillow, dvc, conan and the T36 sqlglot test split are not read. Nothing here is a scored result.

Claim tags: [measured] = observed in our own run, [established] = from the literature or by construction, [hypothesis] = a guess a scored run can support or refute.

## Held-out set for the confirm run, declared before the ablation runs

The confirm run of the winning (learner, regime) uses the next three largest repositories of the same public dataset after Pillow, dvc, conan, sqlglot, the four unreadable ones and the 100 pool repositories, ranked by trajectory count from the per-repository counts file (counts only; no row of theirs was read) [measured]:

| repository | trajectories | tasks |
| --- | --- | --- |
| tox-dev/tox | 606 | 54 [measured] |
| dask/dask | 605 | 56 [measured] |
| pybamm-team/PyBaMM | 524 | 44 [measured] |

Whether the OpenHands reader accepts them is not checked yet; a refusal is reported at the confirm run, never replaced quietly [hypothesis].

One exploratory screen (fly variants, ranking only, pool scoring fold) ran before this declaration; it did not touch these repositories [measured].

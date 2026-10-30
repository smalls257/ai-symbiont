# Core D2 amendment 1: the control manifest (arm C)

Dated 2026-10-30, committed before the first D2 run. It adds the control manifest's hash and counts. It changes no task, arm, measure or decision rule of `2026-10-29-core-d2.md`.

- **Manifest sha256:** `baf92261d2ae103f1e10241d66c2d6d824e5da90d609a4be499ea518e7546184` [measured].
- **Source.** Spark teacher passes on tasks of other repositories, one task per repository: 86 passes in all, none from the six D2 repositories, none a test task or a later candidate [measured]. Counts are in `results/core-d2-train-C-counts.json`.
- **Selection.** The earliest passes by `created_at`, as the prereg says.
- **Disclosed: how the two matching targets were met.** The prereg says C matches A's 68 sessions AND A's 121,600 trained tokens. The first 68 sessions in date order carry 104,627 trained tokens (14% under A). Both targets cannot hold at once, so the token target governs: C is the **smallest date-order prefix that reaches A's trained tokens, 79 sessions with 121,904 trained tokens** (0.25% over A) [measured]. C therefore has more sessions than A, which makes it the stronger control and works against the claim, not for it [established].

# PREREG v2 (FROZEN 2026-11-03 09:54:30 PST, before any v2 scored run): "corrected once, never repeated" for coding. SYNTHETIC, DESIGNED TASK

Supersedes nothing: v1 (`PREREG-corrected-once.md`) was stopped by the owner at 12 of 24 runs for two delivery bugs, fixed in PR #69. Tags: [measured] = a run on this laptop, [hypothesis] = reasoning. Hand-built toy repo and hand-written rules; no speed-of-learning claim.

**Build.** ai-symbiont `origin/main` = `f7cd3353cdfbee9125dc98bf861bb6f8cd23950d` (includes PR #69; fetched 2026-11-03 09:54:30 PST), fresh isolated install `pair/symbiont-src-f7cd335`, plugin `symbiont-co`, service port 7482 (7377 untouched). `install=<sha>` is asserted and logged before every run. Model, flags, harness (`scripts/run_session.sh`, `scripts/chain.sh`: only the build path/sha changed from v1; v1 copies in `scripts/v1/`).

**Unchanged from v1:** repo `base/ledger`, rules R1 (fees at today's rate, payouts at the stored rate), R2 (audit.record on every posted entry), R3 (shares round in the house's favor: fees up, payouts down), hidden checker, tasks S1..S8, 18 rule opportunities per arm, measures (PRIMARY total violations ON vs OFF; SECONDARY tasks with zero violations, visible tests passing, violations by rule, tool calls/tokens, whether notes fired), decision rule (ON better only if ON total < OFF total; ties and nulls reported plainly; N=8 one run each, no significance claim), no rescue (INVALID re-run once as -r2; nothing else), settings backup/restore with diff, no commits or pushes.

**Teaching store: the frozen v1 teach store is REUSED, not re-mined** (the cleaner comparison: same lessons, only the build differs). `pair/data-snapshot-teach`, hash 844effc76f6a776c, including the reflection lesson that contradicts R1, which the fixed build is expected to retire at delivery. Hashes: hidden=340d6e57b2f454ed tasks=d0995ba5d6102231 base=99d7bfa2c1989a11.

**Zero-Spark preflight on the fixed build** (hooks of the v1 OFF sessions S1..S7 replayed against the teach store, `pair/replay-preflight-v2.txt`): a "house rules" note naming the audit, rounding and fee-rate corrections fires at SessionStart in every session; the contradicting reflection fires in none; task-specific rounding/rate notes fire on S3, S4, S5 prompts. (S8 had no v1 session to replay.)

**Arms.** OFF (no plugin, no service) and ON (plugin + service, a fresh copy of the teach store per run), each on all 8 tasks, fresh runs (v1 results are not reused for either arm). ON-F is dropped (supersession is in the product). Order per task: OFF, ON; tasks S1..S8. Run ids `v2-S<n>-off-1`, `v2-S<n>-on-1`. [established]

**Spend.** Cap $8 total for v1+v2; v1 used about $0.89. Rates $0.10/M input, $0.20/M output from `muse.*.jsonl`. Stop and message the coordinator before exceeding it. Install .venv and workspaces deleted at the end. [established]

---
Committed copy, added after the runs. The only changes from the frozen file (sha256 9cf0fcc990790e5814a7fef49c528fc11f366239bf8f4d2e0a04ee85d62d5724) are the claim tags appended to lines 13 and 15 and this note; no rule, arm, task or threshold differs.

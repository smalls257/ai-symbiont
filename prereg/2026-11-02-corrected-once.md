# PREREG: "corrected once, never repeated" for coding. SYNTHETIC, DESIGNED TASK (frozen 2026-11-03, before any scored run)

Everything below is a synthetic, designed experiment: a hand-built toy ledger repo and hand-written house rules. It is the coding counterpart of the Habitat house-rules result. Tags: [measured] = a run on this laptop, [hypothesis] = reasoning. No speed-of-learning claim.

**Build.** ai-symbiont `origin/main` = `bbb31cec1b4f1a5b57802d9b04da5bde61e16697` (fetched 2026-11-03), fresh isolated install `pair/symbiont-src-bbb31ce`, plugin renamed `symbiont-co`, service on port 7482 (7377 untouched). `run_session.sh` and the chain print/assert `install=<sha>` before every run. Model `muse-spark-1.3-contributor`, `--disable-approval --disable-web-tools`, fresh XDG per run, API key only inside the muse subshell. Owner Muse settings backed up before and restored after (diff reported).

**Repo.** `base/ledger`: a toy multi-currency ledger. No document, comment, README line or test message states any rule. Three unstated house rules, each checked by a HIDDEN script (`hidden/checks.py`, never in a run workspace, workspaces live in /tmp/co-ws/<run>/ledger), by behavior on probe scenarios:
- R1 rate: a FEE is converted to USD cents at today's rate; payouts/reversals on a charge (refund, credit, discount, credit note) at the rate stored on the charge. (Cold default observed: stored rate for everything.)
- R2 audit: every entry posted gets an `audit.record(kind, account, cents, ref)` call with the entry's cents.
- R3 rounding: a share of money (percent, fraction, installment) rounds in the house's favor: collected fees up, paid-out money down.
Each task also has a visible test file that passes whether or not the rules are followed (checked with an all-compliant and an all-violating reference implementation: 19/19 pass in both; the hidden checker was validated against 12 knob combinations x 11 tasks, 0 mismatches: `hidden/selftest.py`). [measured]

**Viability (done before this freeze).** First rule set (stored rate for everything, half-up rounding through `money.round_half_up`, audit) was too guessable: 2 cold OFF runs (`runs/viab0-*`) followed stored rate and half-up from the code and missed only audit. Replaced by the set above, then 2 cold OFF runs (`runs/viab-V1-off-1`: R1 pass, R2 fail, R3 fail; `runs/viab-V2-off-1`: R1 fail, R2 fail). Not guessable; those four runs are not scored.

**Session 1 (teaching), `runs/teach-1`.** Task T0 (`restocking_fee`), symbiont ON, empty store. One muse session id across turns (`muse exec --session-id`). After turn 1 the hidden checker ran; each violated rule got its scripted correction as a further turn of the same session ("We never X here; we always Y."; text in `scripts/corrections.py`). Result: turn 1 violated R1, R2, R3; after the three corrections all pass. Then `symbiont repo mine`, then the product's correction-curation step (a Spark session calls `symbiont_correction_candidates` and `symbiont_save_corrections`; `scripts/curate.sh`). Stored: three correction lessons (fee rate, audit, house rounding), plus ONE reflection lesson written by the session's own end-of-turn-1 reflection BEFORE the corrections, which says the OPPOSITE of R1 (fees at the stored rate). Disclosed, not edited. Zero-Spark preflight (`pair/replay-preflight.txt`, hooks replayed on the two cold viability sessions): the wrong reflection lesson fires on both fee-like prompts; the fee-rate correction lesson fires on V1 only; the audit and rounding correction lessons carry no terms and did not fire at prompt time.

**Arms (scored sessions).** 8 new tasks S1..S8 (`tasks/`), same repo, fresh copy per run, each run once per arm:
- OFF: no plugin, no service.
- ON: plugin + service with a fresh copy of `pair/data-snapshot-teach` (the store exactly as the product produced it, wrong reflection lesson included). PRIMARY ON arm.
- ON-F (secondary, exploratory): same, from `pair/data-snapshot-forget` = the snapshot after the developer runs the product's own `symbiont forget --lesson w-ac33036dcd3d` on the wrong reflection lesson.
Order per task: OFF, ON, ON-F; tasks S1..S8 in order. Snapshots are never written back; the three snapshot hashes are recorded in REPORT.md.

**Opportunities (rule x task pairs that the hidden checker scores; others are "na").** R1: S1,S2,S3,S4,S7,S8 (fee tasks S1,S2,S7; payout tasks S3,S4,S8 pass by the natural default and only fail if a lesson is over-applied). R2: all 8. R3: S1,S3,S4,S7. Total 18 per arm.

**Measures.** PRIMARY: total rule violations over the 18 opportunities, ON vs OFF (lower is better). SECONDARY: tasks with zero violations (of 8); visible tests passing (all tests in the run's workspace after the canonical visible test is restored); violations by rule; ON-F vs OFF; tool calls and tokens; whether any symbiont note fired in the ON sessions (hook trace/event log). A checker `error` (function missing or crashing) is reported separately and counted as neither pass nor violation; if visible tests fail, the run is still reported.

**Decision rule.** ON counts as better only if ON total violations < OFF total violations. Equal or greater is reported as a tie or null. N = 8 tasks, one run each: a pilot-sized signal, no significance claim. Nothing is dropped; every run is listed. [established]

**No rescue.** INVALID run (auth/quota error in stderr or no output) is re-run once as `-r2` and the first reported INVALID; no other re-runs; no prompt, rule, checker or snapshot edits after this file. Amendments are new dated files written before results.

**Spend.** Cap $8 for this experiment; ledger-fitted rates $0.10/M input and $0.20/M output tokens from `muse.*.jsonl` summaries. Stop and message the coordinator before exceeding it. [established]

**Hygiene.** Spark sees only this synthetic repo and template text; nothing Spark wrote enters any training set. No commits or pushes to ai-symbiont-public. `.venv` of the install deleted at the end.

**Frozen hashes (sha256 of sorted file hashes, first 16 hex).** hidden=340d6e57b2f454ed tasks=d0995ba5d6102231 base=99d7bfa2c1989a11 snapshot-teach=844effc76f6a776c snapshot-forget=70a63c1bbd93b292. Install sha bbb31cec1b4f1a5b57802d9b04da5bde61e16697.

---
Committed copy, added after the runs. The only changes from the frozen file (sha256 3ffaac31ba46f4234896da0f52a3424a650bf05496f2a21a48663ff3b62a0413) are the claim tags appended to lines 11, 27 and 31 and this note; no rule, arm, task or threshold differs.

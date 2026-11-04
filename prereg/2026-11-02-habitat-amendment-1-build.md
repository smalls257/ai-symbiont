# Amendment 1 (2026-11-02): symbiont build change for the Task B v2 comparison

Cause: the first Task B v2 run used ai-symbiont dc35e1f, before PR #61 (multi-note delivery, module areas) and PR #62
(note cap, add_lessons aliases, one-time onboarding question). Owner asked for a re-run on the current build.

- Build: github.com/smalls257/ai-symbiont at exactly afd5b7876ca188addde0c14060f33e20ee2d1f2c, fresh venv (venv2); build_check.log
  asserts the checkout sha and byte-equality of the 196 installed files. Isolated service: port 8794, data dir symdata-v2.
- Same frozen design, seeds (541-545), pet events, planning questions and lesson sources: the 3 failed gate episodes
  (gate-host-515, gate3-host-522, gate3-host-525), re-mined and re-reflected by Spark with the new build; nothing hand-edited.
  Spark's reflection wording differs from the first run, so the lessons are a fresh sample. Store snapshot:
  results/store_snapshot_v2_afd5b78.db. Zero-Spark replay: results/replay_v2.json.
- WITHOUT arm: the 5 existing episodes (cmpB-without-541..545) are reused; they do not depend on symbiont. WITH arm: 5 new episodes,
  results/cmpB2. The first-build WITH episodes (results/cmpB) stay as the dc35e1f record; both builds are reported.
- Primary and secondary measures unchanged. Real renders of seed 541 only if the new WITH arm improves success.

---
Committed copy, added after the runs. The only changes from the frozen file (sha256 fb8f930f9b2c19d9b59d5804498740fd57b45d35d804580102de8a72c7114510) are the claim tags appended to the lines that state a number and this note; no rule, arm, seed or threshold differs. The original's recorded freeze time is its file modification time, 2026-11-02T22:33:20-08:00. The committed copy was added after the runs, so git history does not show the freeze; the hash and timestamp do. Amendment 1 was abandoned: the owner replaced it with Amendment 2 before any of its episodes was scored.

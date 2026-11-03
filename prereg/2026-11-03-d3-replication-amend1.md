# PREREG D3 replication, amendment 1 — dated 2026-11-03, written before the first replication run

Coordinator approvals (2026-11-03): per-chain lock files are approved (the shared `muse.lock` existed to serialize Spark use across agents and to guard the owner's Muse settings; the isolated config removes the settings reason; Spark allows 150 requests per minute).
**Rate-limit rule (not in the frozen prereg):** a run that fails ONLY with rate-limit text (HTTP 429 / "rate limit" in `muse.stderr`, no other cause) counts as INVALID (infrastructure), not as an outcome. It is re-run once under `-r2` and listed in the report with both attempts. After the first such run, the remaining pairs run on ONE chain (chains 2 and 3 stop after their current run; chain 1 continues the remaining pairs in order). A run INVALID twice stops that chain and is reported; no run is dropped for its outcome. Everything else in `PREREG-D3-replication.md` stands (arms, primary Fisher test, cap $20, no pooling with v3). [established]

---
Committed copy, added after the runs. The only changes from the frozen file (sha256 1edf8aa2b9dde71f2b3b30b14826e93673c25e2b8030fc78831d8c1f601ef2df) are the claim tag appended to the line(s) the claim-tag gate flagged, and this note; no rule, arm, task, threshold or number differs.

# PREREG D3 replication, amendment 2 — dated 2026-11-03, written before any replication result

Cap: the coordinator raised the D3 total cap from $20 to $24 (covers the 10+10 replication plus about $1 for the unscored showcase pair, which is not counted by the chains' token ledger). The three running chains were started with a $20 guard compiled into their shell functions (refuse a run when spent + $0.8 > $20). If any chain stops with `D3R<n>-CAP` while pairs remain, the unfinished pairs are run afterwards by a continuation chain with the same run ids, the same snapshot/build/prompt/checker and a $24 guard (minus $1.8 reserve for the showcase and margin); this is finishing the pre-registered 10+10, not a rescue, and the log states which pairs ran in the continuation. Nothing else changes. [established]

---
Committed copy, added after the runs. The only changes from the frozen file (sha256 856347b08e21298d20d31af90c2c337a366c03343840cca5eac16d27274bf554) are the claim tag appended to the line(s) the claim-tag gate flagged, and this note; no rule, arm, task, threshold or number differs.

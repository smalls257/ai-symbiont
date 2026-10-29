# Amendment 1 to the reasoning-strength gate prereg

Dated 2026-10-27, committed before the full run. The smoke run (2 items per
arm, 4 requests, no scored result used) crashed while writing its results:
the secondary same-file count built a coding gold for a Freedoom item and
raised `KeyError`. The fix returns false for non-coding items before building
the gold. Nothing else changed: not the items, arms, seed, sampling, scoring
definitions or decision rule. [established]

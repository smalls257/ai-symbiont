# Amendment 2 to the reasoning-strength gate prereg

**FROZEN 2026-10-27.** Committed before the results file is rebuilt under the guard.

Amends: prereg/2026-10-28-reasoning-strength-gate.md

Claim tags: [measured] = observed in our own run, [established] = known from
the literature or the code's own documented behavior, [hypothesis] = a guess
the run can support or refute.

This amendment supersedes amendment 1
(`prereg/2026-10-28-reasoning-strength-gate-amendment-1.md`) for the guard's
chain, because amendment 1 lacks the FROZEN marker, the claim-tags paragraph and
the Amends line. Amendment 1 is not edited. Its text, restated word for word:

> Dated 2026-10-27, committed before the full run. The smoke run (2 items per
> arm, 4 requests, no scored result used) crashed while writing its results:
> the secondary same-file count built a coding gold for a Freedoom item and
> raised `KeyError`. The fix returns false for non-coding items before building
> the gold. Nothing else changed: not the items, arms, seed, sampling, scoring
> definitions or decision rule. [established]

No rule, item, arm, seed or scoring changed. The results file is rebuilt from the
existing replies log under `--scored --prereg` with no new Glimmer request, and
no number changes. [established]

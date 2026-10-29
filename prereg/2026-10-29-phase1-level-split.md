# Declaration: Freedoom Phase 1 training / validation / held-out level split

**Declared 2026-10-29, before any game, smoke run or engine load on a Phase 1 map.** The rule is fixed
by this file and by `src/symbiont/act1/levels.py`; a later change is a new dated file.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or the
code's own documented behavior, [hypothesis] = a guess the run can support or refute.

## Why

Only freedoom2.wad (Phase 2, MAP01 to MAP32) has been through the walker check. Phase 1
(freedoom1.wad) adds 36 more maps in a different style [established: the WAD directory holds E1M1 to
E4M9], so lessons can be tested on situations that recur across many maps.

## Rule

- Maps are numbered in play order, `position = (episode - 1) * 9 + map`, so E1M1 is 1 and E4M9 is 36.
- Every fourth position is held out, the same rule as the Phase 2 split: E1M4, E1M8, E2M3, E2M7,
  E3M2, E3M6, E4M1, E4M5, E4M9. The other 27 maps train.
- Validation maps are chosen after the smoke test, as in Phase 2: every sixth passing training map,
  at least three, never used for selection or lesson mining.
- A map that fails the smoke test is dropped and listed with the reason, never replaced.
- Held-out maps get the static route check and an engine load with zero decisions before the freeze
  of any prereg that scores them. No episode on a held-out map before that.
- The Phase 2 held-out maps stay untouched. Phase 1 and Phase 2 results are never pooled without
  saying so.

## Variation

Skill levels 2, 3 and 4 and fresh start seeds, as in Phase 2 training. Starting health and ammo are
not varied: the engine adapter sets neither, and changing a start condition is a new, separately
declared change.

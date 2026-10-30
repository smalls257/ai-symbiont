# Plug round 4: the primary situation set, fixed on counts before any model answers

Dated 2026-10-29. Committed before the round-4 prereg is drafted and before any model answers any round-4 scored situation. It fixes which real recurrences form the primary, using counts alone.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or by construction, [hypothesis] = a guess the run can support or refute.

## Definitions

- **Recurrence.** A failed command in a later, different task of a repository whose exact (shown command, error line) matches a lesson mined from an earlier task of that repository (`scripts/routea/plug_r4_recur.py`, key `exact`). Distinct (later task, key) pairs count once; repeats within one task do not count [established, by construction].
- **Never-read repository.** One whose rows no experiment read before round 4. **Meta2-only repository.** One the meta2 experiment exported (one trajectory per task), which neither plug nor any judge ever read.

## Counts at this note (repositories on disk)

- Never-read: 72 exact recurrences in 37 repositories [measured].
- Meta2-only: 172 exact recurrences in 45 repositories [measured].

## The rule

1. The about 1,291 repositories of `nebius/SWE-rebench-openhands-trajectories` that were never downloaded are exported (public data, code-only processing) and their exact recurrences counted with the same script; they are never-read repositories.
2. If never-read exact recurrences reach **150 or more** before the round-4 prereg freezes, the primary is never-read repositories only, and meta2-only repositories become a secondary row.
3. Otherwise the primary is never-read plus meta2-only repositories (now 244 in 82 [measured]), with meta2's earlier read disclosed.
4. In either case the secondary rows are: the verified subset (later recurrences that were themselves fixed with the same fix), loose-key recurrences (normalized command), Spark-written paraphrases (a prompt separate from the nightly-training one), and round-3-style situations labeled "string-match level".
5. This choice is made on counts only, before any model answers any of these situations, and no situation of any scored repository enters training.

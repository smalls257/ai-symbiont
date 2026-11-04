# Benchmarks and evaluation

Every number below is copied from a file in `results/` or a research note in `docs/research/`; nothing here is new. Each evaluation was pre-registered: the plan was committed to `prereg/` before the scored run, and amendments are new dated files. The evaluation code lives in `src/symbiont/eval`. `REPRODUCE.md` recomputes the headline numbers from the committed result files (`uv run python scripts/reproduce/check_numbers.py`).

Claim tags: [measured] is observed in our own run, [established] is known or true by construction, [hypothesis] is a guess a run can support or refute. Every model run used Muse Spark, Meta's model.

## Index

| Evaluation | Metric and value | Result file | Prereg | Research doc | Tag | Method in one line |
|---|---|---|---|---|---|---|
| Precision of notes (89 unseen open-source projects) | 0 wrong notes in 501 items shown; exact upper bound 0.73% | `results/plug-r4-scored-primary.json`, `results/plug-r4-bounds.json` | `prereg/2026-10-29-plug-round4-DRAFT.md` (frozen at a8f428c) and `prereg/2026-10-30-plug-round4-nightly-amendment.md` | `docs/research/2026-10-30-plug-round4-result.md` | [measured] [pre-registered] | 251 real later repeats and 250 negative items; a small trained judge and a ranker had to agree before a note was shown. The test bugs were planted. |
| Rule only in maintainer reviews (D3, sqlglot PR #7433) | Runs with a forbidden `.copy()`: 7 of 10 without symbiont, 0 of 10 with it; p = 0.003 (Fisher exact, two-sided) | `results/d3-replication.json` | `prereg/2026-11-03-d3-replication.md` (with `-amend1`, `-amend2`), `prereg/2026-11-03-d3-v3.md`, `prereg/2026-11-03-d3-v2.md`, `prereg/2026-11-03-d3-oracle-addendum.md` | `docs/research/2026-11-03-d3-public-review-rule.md` | [measured] [pre-registered] | One real task from a public SQL library, 10 runs per arm; the rule was learned from maintainer reviews of earlier pull requests. One repository, one rule, one task. |
| Corrected once, never repeated | Rule violations: 16 without symbiont, 0 with it, over 18 chances in 8 tasks; clean tasks 0 of 8 without, 8 of 8 with | `results/corrected-once-v2.json` | `prereg/2026-11-03-corrected-once-v2.md` (first version: `prereg/2026-11-02-corrected-once.md`) | `docs/research/2026-11-03-corrected-once-result.md` | [measured] [pre-registered] | The user states three rules once; the agent does 8 new tasks, one run each, graded by a hidden checker. Synthetic, designed task. |
| Freedoom (Muse Spark plays Freedoom via ViZDoom) | Game score (0 to 1) +0.16 against no rule, interval [0.106, 0.218], across 240 new games | `results/evolve-replication.json` | `prereg/2026-11-01-evolve-replication.md` | `REPRODUCE.md` (recomputation table) | [measured] [pre-registered] | A rule card the model wrote from its own failed games, against no card, on newly generated maps. The first test of the card is `results/evolve-confirm.json`. |
| Nightly training | 61% of repeats approved, 97.8% of approved notes right (5 wrong of 924 items, 227 answered); untrained judge approved 0% | `results/plug-r4-smith-decision.json` | `prereg/2026-10-31-code-fix-lessons.md` | `docs/research/2026-10-31-code-fix-lessons-result.md` | [measured] [pre-registered] | The small judge is trained for one night on the project's own history, then scored on code it has not seen. Synthetic injected bugs, two repositories. |
| Habitat (home robot sets the table) | Episodes solved: 4 of 5 with symbiont's notes, 0 of 5 without | Not in this repository's `results/`; reported on the project page | Not in this repository's `prereg/` | None in `docs/research/` | [measured] [pre-registered] | Notes came from the robot's own two failed attempts, then 5 new episodes in Meta's Habitat simulator. |
| House rules (home robot) | House rules broken: 30 across 6 episodes without the owner's corrections, 0 across 6 with them | Not in this repository's `results/`; reported on the project page | Not in this repository's `prereg/` | None in `docs/research/` | [measured] [pre-registered] | The corrections were scripted for the demo. |

The Habitat and house-rule rows are listed so the README's claims have an index entry; their raw files live outside this repository, which is why those cells say so rather than name a file.

## Where the code is

- `src/symbiont/eval`: the replay, selection, scoring and report code behind the offline evaluations.
- `scripts/reproduce`: `check_numbers.py` and the one-command demo.
- `results/`: counts, ids and labels as JSON only. `prereg/`: the frozen plans.

# core: the Decider slot and its fillers

See root CLAUDE.md for the repo rules. This file covers `src/symbiont/core/`.

**Purpose.** Decide, from a situation and learned state, whether to warn and what to recall. Fillers: `Counters`, `Similarity`, `Mushroom` (the fly circuit), `LogisticWarner` (Route A; weights passed in, fitted by `scripts/routea/fit_warner.py`), plus the 86-feature vector, notes in domain prose, option A delivery rules (`note_rules`) and the memory model's prompt and three-part line (`memory_note`).

**Violations prevented: Infected Core and Paper Tiger.** The decision math is a function of (features, state) that passes the Airplane Test, so it runs and is tested with no network, store or harness. A network gets a job only where it beats the simple option (likely the adapter picker [hypothesis]); on the same replay a tie is reported as a tie, and the brain is never shown deciding what the classifier decides.

## Invariants
- `Decider` protocol: `decide(x, situation, state)`, `learn(x, outcome, state)`, `initial_state(seed)`. State is passed in and returned; no hidden mutation, deterministic given the seed.
- A `Decision` that stays quiet carries a `reason_none`, so a silent learner differs from a broken one.
- `rule_relevance.py` ranks the rule-bearing lessons relevant to a prompt or failure. A rule fires on one strong signal (its own file or area touched, or a hit on a term or area the writer tagged), or on weak words worth at least `MIN_WEAK_SCORE` (identifier-like tokens weigh 2, other distinctive words 1). `rule_terms.py` decides which words count: stopwords, generic talk (`because`, `field`, `table`, `error`) and words most of the repo's lessons share are worth nothing. The lesson's file weighs `FILE_WEIGHT` (4), a sibling file in its module directory `AREA_WEIGHT` (3; generic directories such as `src/` and `tests/` never count; `areas_of_files` also fills a written lesson's missing areas). `file_scoped_rules` matches only the lesson's own file by whole trailing path parts (relative or absolute), for successful reads and edits. The gate delivers up to `MAX_RULE_NOTES` (2) per event, each cut at `MAX_NOTE_CHARS`: one slot let the lesson about the file being edited starve a second relevant one. `why` lists every signal with its weight, which the service writes to the event log as `fired_by`; `failure_signature.py` normalizes a failure for matching.
- `house_rules.py` (Violation prevented: Paper Tiger): a developer's correction is a house rule, and so is a rule lesson with a PR link (`Rule.is_pr_ruling`; a review ruling is the team's correction however Spark filed it). `standing_corrections` ranks own corrections before PR rulings, then priority, then newest. `retired_by_corrections` retires a written lesson that is not itself a correction when a correction written after it (write order; reflections carry no session id) shares at least `SAME_SUBJECT_SCORE` of distinctive words or tags with it; the correction wins, the older lesson never fires. Two PR rulings never retire each other (an unrelated ruling that shares a dialect name once silenced a DuckDB copy ruling); only an own correction retires a ruling. `standing_corrections` / `standing_sentence` build one note of at most `MAX_STANDING` (3) corrections, high priority first then newest, within `MAX_NOTE_CHARS`, so a correction with no terms still reaches the agent. A mined lesson is never retired.
- `quoted_rule.py`: a PR lesson with the reviewer's `quote` is said as `In this repo, a maintainer said on PR #N: "<quote>" (<lesson>).`, quote first and whole; within `MAX_NOTE_CHARS` the lesson's sentences give way, never the quote. Used by the rule, file-trigger and house-rules notes.
- `repeat.py` is the exact-repeat rule (day-one note): a stored, fixed failure with the same normalized signature as a live one, planned failures excluded by the miner's own filter.
- Notes are domain prose: no scores, feature names, thresholds or activations. A lesson renders as what happened, how it was resolved (or that no fix was found), and the check to run.
- No claim about speed of learning; "a learner built on the fly's real circuit".

## Imports
- May import: `records`, `miner`, numpy. Must not import: store, service, delivery, readers, eval, routeb, act1, time, sockets, subprocess.

## Commands
`uv run pytest tests/core tests/test_boundaries.py -q` and `uv run lint-imports`

## Review focus
Any new import. Any function near the 30-line cap. Does a new filler get compared with counters and the classifier before it is believed?

# core: the Decider slot and its fillers

See root CLAUDE.md for the repo rules. This file covers `src/symbiont/core/`.

**Purpose.** Decide, from a situation and learned state, whether to warn and what to recall. By owner decision the logistic classifier on the 86-feature vector is the live warner; it lives in eval code today, not yet in core. the fillers (`Counters`, `Similarity`, `Mushroom` (the fly circuit)) are a swappable slot with no loyalty to the fly, each judged against it. Notes are domain prose and structured: what happened, how it was resolved, the check to run.

**Violations prevented: Infected Core and Paper Tiger.** The decision math is a function of (features, state) that passes the Airplane Test, so it runs and is tested with no network, store or harness. A network gets a job only where it beats the simple option (likely the adapter picker [hypothesis]); on the same replay a tie is reported as a tie, and the brain is never shown deciding what the classifier decides.

## Invariants
- `Decider` protocol: `decide(x, situation, state)`, `learn(x, outcome, state)`, `initial_state(seed)`. State is passed in and returned; no hidden mutation, deterministic given the seed.
- A `Decision` that stays quiet carries a `reason_none`, so a silent learner differs from a broken one.
- Notes are domain prose: no scores, feature names, thresholds or activations.
- No claim about speed of learning; "a learner built on the fly's real circuit".

## Imports
- May import: `records`, `miner`, numpy. Must not import: store, service, delivery, readers, eval, routeb, act1, time, sockets, subprocess.

## Commands
`uv run pytest tests/core tests/test_boundaries.py -q` and `uv run lint-imports`

## Review focus
Any new import. Any function near the 30-line cap. Does a new filler get compared with counters and the classifier before it is believed?

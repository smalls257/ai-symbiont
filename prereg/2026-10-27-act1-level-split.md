# Pre-registration: Act 1 training / held-out level split

**DRAFT, not frozen.** The owner freezes it with a commit that changes only this status line.

Claim tags: [measured] = observed in our own run, [established] = known
from the literature or the code's own documented behavior, [hypothesis] =
a guess the run can support or refute.

## Question

Which levels may Task 39 meta-training and Act 1 learner development see?

## Split rule

- Every fourth map of freedoom2.wad is held out: MAP04, MAP08, MAP12, MAP16,
  MAP20, MAP24, MAP28, MAP32 (the rule is fixed by this file).
- The other 24 maps train.
- MAP01 trains because development runs already played it [measured] (the Act 1
  handoff records a scripted go_to(exit) finishing MAP01).
- Difficulty rises roughly with map number, so this rule spreads the held-out
  levels across difficulty [hypothesis].

## Use

- Held-out levels appear only in scored Act 1 / Task 39 evaluation.
- The collector (`scripts/act1/collect_episodes.py`) refuses them through
  `levels.require_training`.
- No episode log, feature fit or threshold choice may read them.

## Episode records and pain tags

Not part of this prereg (owner decision). They live in code:
`src/symbiont/act1/episode_records.py` and `src/symbiont/act1/game_pains.py`.

## Not decided here

Scored-run metrics, seeds and N belong to the Task 27 prereg.

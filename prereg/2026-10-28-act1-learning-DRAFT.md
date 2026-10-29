# Pre-registration draft: Act 1 learning, plain versus personal Glimmer (plays Freedoom via ViZDoom)

**DRAFT, not frozen.** The owner freezes it with a commit that changes only this status line, before any evaluation episode is played. The collector (`scripts/act1/collect_episodes.py --scored FILE`) refuses held-out levels unless the file's first bold line starts with the freeze mark and the file is committed and unchanged.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or the code's own documented behavior, [hypothesis] = a guess the run can support or refute.

## Question

Does a Freedoom LoRA adapter, trained with the Route B recipe on lessons from Glimmer's own play mistakes, make Glimmer repeat fewer mistakes: on levels it played before (efficiency), and on levels it never saw (transfer)?

## Hypotheses

- H1, same level [hypothesis]: on training levels Glimmer played during history collection, personal Glimmer makes fewer pain points per episode than plain Glimmer, paired by level and seed.
- H2, held-out level [hypothesis]: on held-out levels (never played, never in any lesson), personal Glimmer makes fewer pain points per episode than plain Glimmer, paired by level and seed. The lessons' checks are general habits ("check the Doors line before open_door()"), so a benefit there would mean the habit transfers.

## Arms

| Arm | Label | What differs |
|---|---|---|
| plain Glimmer | floor | adapter scale 0 on every request |
| personal Glimmer | under test | the Freedoom adapter at scale 1 |

Both arms ask one llama-server that holds the adapter (`glimmer.plain_and_personal`): same Q4_K_M base, same build, same prompt, same sampling (temperature 0.6, reasoning low, 1500-token reply cap). They differ only in the per-request adapter scales [established: the arms' request bodies are compared in `tests/act1/test_chat_reply.py`]. No counters row applies: Act 1 has no fly learner. No ceiling arm: a lessons-in-prompt ceiling is a possible later run and is not part of this file.

## Data

- History (adapter training data): plain Glimmer on the production server, training levels MAP01, MAP02, MAP03, MAP05, MAP06, seeds 1 and 2, a 16-decision cap. Stop rule: if fewer than 20 lessons are selected, add MAP07 and MAP09 at seed 1, then stop at 14 episodes whatever the count.
- Lessons: `build_lesson_set.py` with its defaults (at most 40 lessons, at most 10 per check, repeated mistakes first). Each lesson gives two card rows and one situation row.
- Training: the Route B recipe (`routeb/prep`: rank 16, alpha 32, v/o plus MLP, 8 epochs, batch 4, lr 1e-4), converted to a GGUF adapter.
- Evaluation, same level: MAP02 and MAP03 at seeds 3 and 4 (seeds not used in history), both arms: 8 episodes, 4 pairs.
- Evaluation, held-out level: MAP04 and MAP08 at seeds 3 and 4, both arms: 8 episodes, 4 pairs.
- Decision cap 16 in every episode. The two arms alternate on each level and seed. Two collector processes (one per condition) share the server's two slots.

## Metrics

- Primary: pain points per episode (every pain tag in the episode's records: wall bump, room re-entered, room re-checked, wasted move), paired difference personal minus plain per level and seed.
- Secondary: exit reached (yes or no); decisions to the exit (episodes that exit; capped episodes are reported as not reaching it, never imputed); Glimmer tokens per episode (server-counted prompt and completion tokens); repeated mistakes per episode (the demo counter: decisions whose pain repeats one already made in the same episode).
- Every row prints both arms; plain is labeled floor, personal under test.

## Decision words

Per condition, over its 4 pairs (ties count against H):

- "fewer pain points" when personal is lower in all 4 pairs and the mean paired difference is at most -2 pain points.
- "more pain points" when plain is lower in all 4 pairs and the mean paired difference is at least 2.
- "no difference shown" otherwise. With 4 pairs, 4 of 4 in one direction happens by chance with probability 1/16 per direction [established: sign test].

The same-level and held-out verdicts are reported separately. A "fewer" on the same level with "no difference shown" held out is reported as efficiency without shown transfer, never as learning to learn.

## Known limits

- Few episodes: 4 pairs per condition. A real effect of a few pain points can fail to show [hypothesis]. Temperature 0.6 adds within-pair noise that seeding the game does not remove.
- Level design differences: held-out levels are different maps, with their own doors, keys and enemies, so held-out pain counts are not comparable with same-level counts. Only within-pair differences are compared.
- Rooms are map sectors, so a door sector or a stair step counts as a room; room re-entered tags therefore include some walking through doorways back and forth [established: game_pains.py].
- The adapter is trained on Glimmer's own plain play; its lessons only cover mistakes plain Glimmer made in history, at a 16-decision cap.
- Training rows answer in the user channel without a reasoning turn (the Route B recipe); during play Glimmer reasons first at low strength. Whether the adapter's effect survives the reasoning turn is open [hypothesis].
- The adapter is trained on bf16 weights and served on the Q4_K_M base (the Route B ruling) [established: routeb-prep-report].
- Per-request adapter scales on the OpenAI-compatible chat endpoint are a llama-server feature the first GPU slot must confirm with one plain and one personal request before any episode [hypothesis until then].
- No speed-of-learning claim is made.

## Not decided here

The Glimmer-hours budget and the GPU slot are the owner's call; the estimate is in `act1-learning-report.md`.

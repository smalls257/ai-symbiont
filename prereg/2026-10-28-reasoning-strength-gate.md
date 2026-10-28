# Pre-registration: the reasoning-strength go/no-go (day-2 gate, Task 37)

**FROZEN 2026-10-27, committed before any model reply to an item exists.**
After this commit only a dated amendment file may change anything, and an
amendment cannot change the items, the arms, the seed, the sampling settings,
the scoring definitions or the decision rule. Spec section 4.5 (job 3) is the
source of the question.

Claim tags: [measured] = observed in our own run, [established] = known from
the literature or the code's own documented behavior, [hypothesis] = a guess
the run can support or refute.

## Question

A small learner might choose Glimmer's reasoning strength at each step. That
choice is only worth building if three things hold together: plain Glimmer at
"Reasoning strength: low" is nearly as good as at "Reasoning strength: high",
low is much cheaper, and this holds on some items and not others. If the
answer is the same everywhere there is nothing to choose and the feature is
dropped. This is a screen on plain Glimmer with no learner in it. It makes no
claim about how quickly anything learns. [hypothesis]

Violations prevented: **Paper Tiger** (building a chooser nobody needs because
the spec said "build it") and **Silent Fallback** at the claim level (a rule
that moves after the numbers are seen).

## Machines and process rules

- Model: `Muse-Glimmer-30B-KQuant-17GB-Q4_K_M`, local Glimmer only, through
  `symbiont.egress` with `Endpoint.LOCAL_GLIMMER`. No Spark, no remote API.
  The address comes from `SYMBIONT_GLIMMER_URL` and is never committed.
- One request at a time, never two: one of Glimmer's two slots is busy with a
  calibration run. Wall-clock is therefore measured on a shared machine and is
  noisy. [established, by setup]
- The laptop builds the Freedoom items (headless ViZDoom) and orchestrates.
  No training anywhere.
- Coding trajectories are read-only copies of public sqlglot SWE-rebench runs
  of Glimmer itself. Their text stays in gitignored `data/`; `results/` holds
  ids, counts and labels only.
- No model reply to any item was read or computed before this commit. Item
  construction (below) uses only the game and the recorded trajectories.
- A crash or bug fix after this commit is a dated amendment saying what
  failed and what changed, committed before the re-run. A re-run without an
  amendment is not allowed. Resuming an interrupted run from its replies log
  is not a re-run: the same request, same seed, is simply not repeated.

## Items (30, fixed here by procedure and seed)

**Freedoom decisions, 20.** The game is Freedoom (`freedoom2.wad`), played via
ViZDoom, maps MAP01 and MAP02. For each map, with `random.Random(20261030)`,
the player is warped to a random point inside the map's bounding box, settled
for 4 tics, then turned for a random number of tics from 0 to 40. The state is
described by `act1.env_text.describe` with the route hints of
`route_hints` (the navmap) added, exactly as Act 1 shows it. The prompt is
`act1.episode.build_prompt(observation, [])` (no history), behind the system
line "Reasoning strength: low" or "Reasoning strength: high". Points that are
not walkable floor, or from which the route finder has no route to any exit,
key or closed door, are skipped. MAP01 contributes the first 11 accepted
points. MAP02 contributes the first 9 accepted points with at most 7 of one
oracle kind (a probe found only 9 of 10 within 1,500 attempts, so the split is 11 and 9 [measured]). The warped states are synthetic positions, not a played episode.
The ids are `doom-MAP01-01..11` and `doom-MAP02-01..09`, in acceptance order.
[established, by construction]

**Oracle (the best next action).** From the state's route hints: `go_to(exit)`
if a route to an exit exists with the keys held; otherwise go_to the nearest
unheld key by walking route; otherwise go_to the nearest closed door by
walking route. This is the repo's own navmap, fixed by the map before any
model is asked.

**Coding steps, 10.** Ten solved Glimmer trajectories on sqlglot, all with
`resolved: true` in the calibration log at the time of selection, read-only
copies from the desktop: instance-run pairs `1309/screen-run1`,
`1367/screen-run1`, `1379/screen-run1`, `1782/screen-run1`,
`1782/confirm-run2`, `1944/screen-run1`, `2095/screen-run1`,
`2443/screen-run1`, `2529/screen-run1`, `2658/screen-run1`. (Nine distinct
tasks: only nine tasks were solved at selection time, so one task contributes
two runs. The two runs of 1782 are not independent.) The item step is the first
assistant action that follows at least 3 earlier actions and edits a file of
the trajectory's final passing patch (the command matches an edit pattern:
`sed -i`, `cat >`, `>>`, `tee`, `patch`, `git apply`, `apply_patch`,
`.write(`, `.write_text(`, `str_replace`, `perl -pi`) and carries that file's
full repo path, so a scratch copy elsewhere is not the step. The request is
the recorded conversation before that action (system line swapped per arm) and
the one-tool `bash` schema of mini-swe-agent. The step's gold is the file it
edits and the function names (`def NAME`) in that file's hunk headers or added
lines in the final patch. Gold steps are computed from the trajectories alone.
[established, by construction]

## Arms and sampling (identical but for one line)

- **low**: system line "Reasoning strength: low". **high**: "Reasoning
  strength: high". Nothing else differs between arms.
- Each item is sent once per arm. Temperature 0.6, Act 1's `REPLY_TEMPERATURE`.
  Act 1 sets no sampling seed, so the gate fixes request seed 20261030, the
  same for both arms and all items. [established, from the code]
- `max_tokens` 3000 for both arms and both domains. Act 1's cap of 1500 is
  raised because the high arm would otherwise be cut off by the cap rather than
  by its own choice; the calibration uses 4096 and the run must fit an hour at
  roughly 12 tokens per second [measured]. A reply cut off by the cap (`finish_reason`
  "length") is a failure for that arm and its tokens are the cap. [established, by setup]
- Arm order alternates by item index (low first on even items) so drift on the
  machine does not favor one arm.
- "fixed-low" and "fixed-high" are these two arms read as plain policies and
  are reference rows. A third row, "hindsight chooser" (low when low succeeds,
  else high when high does, else low), is the ceiling row for any future
  chooser. There is no floor row: no chooser exists yet.

## Scoring (exact, fixed before data)

- **Freedoom.** The reply is parsed with `act1.strategy.parse_strategy` exactly
  as Act 1 parses it (strict, no default move). The first move line is the
  scored action. Success: it is `go_to(T)` with T the oracle kind word (`exit`,
  `key` or `door`) or, for a key, the key's exact label (case-insensitive); or
  it is `walk_to(T)` for the oracle's exit or door when that thing is in view
  in the state, or the key's label. Labels otherwise: `wrong_move`, `invalid`
  (not a valid strategy), `truncated`.
- **Coding.** The scored action is the first `bash` tool call of the reply.
  Success: its command names the gold file (the full repo path or the bare file
  name as a whole token) and, when the gold has `def` names, mentions at least
  one of them as a whole word. Labels otherwise: `wrong_file_or_function`,
  `no_action` (no tool call), `truncated`. The same-file-only reading is
  reported as a secondary count and is not used in the decision rule. The
  "run the same test" clause is not used: every gold step here is an edit.

## Measures

Per item and arm: success (0 or 1), completion tokens (the server's
`usage.completion_tokens`, which includes hidden reasoning), wall-clock seconds
of the request, and the scored label. Pooled over the 30 items, plus a
per-domain breakdown that is reported and not used in the rule.

## Decision rule (numbers, direction, tie-break; all three must hold)

Let N be the number of items (30). Let `r_i` = low completion tokens over high
completion tokens on item i, and `m` = the median of `r_i` over all items.

1. **Nearly as good.** `success_high - success_low <= 0.10`, both rates pooled
   over all items. Low being better satisfies it.
2. **Much cheaper.** `m <= 0.50`.
3. **Some items and not others.** Call item i *differing* if low fails where
   high succeeds, or `r_i > 2m` or `r_i < m / 2` [established]. At least 25% of the items
   (8 of 30, rounding up) must differ.

All three hold: **GO**, build the per-step reasoning-strength chooser (job 3).
Any one fails: **NO-GO**, drop job 3 and keep Glimmer at "Reasoning strength:
low" as Act 1 does today. A tie on a threshold counts as holding. An item with
zero completion tokens in either arm is a failed request, not data: the run
stops and is resumed, never scored. These numbers were set from the owner's
brief (10 points, half the tokens, a quarter of the items, 2x) [hypothesis] and refined
only in the definition of "differ" (a per-item ratio band around the median)
and "median" (median of per-item ratios), both fixed here before any data.
[hypothesis, thresholds are judgment]

## Estimated spend

No money: local Glimmer only. About an hour of Strix time at roughly 12
generated tokens per second, one request at a time. [hypothesis]

## Output

`results/reasoning-strength-gate.json`: per-arm rows (role: reference for
fixed-low and fixed-high, ceiling for the hindsight chooser), per-item 0/1
strings in item order, token and second totals and medians, label counts, the
three rule conditions and the verdict. Counts, ids and labels only. A full
report with caveats is written to a local, uncommitted file.

## Caveats stated in advance

- Thirty items cannot resolve small differences; the result is a screen. [established]
- Freedoom states are warped, not played, and MAP01 may supply a single oracle
  kind, which would make those items easy for both arms. [hypothesis]
- The coding score measures where the first command points, not whether the
  fix would pass. [established]

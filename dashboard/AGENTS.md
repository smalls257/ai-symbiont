# dashboard: static replay page

See root CLAUDE.md for the repo rules. This file covers `dashboard/`.

**Purpose.** One static HTML/JS page that replays `results/*.json` and `runs/*/events.jsonl` as lanes, a scoreboard and a brain panel, for the video and the judges.

**Violation prevented: Paper Tiger (and Black Box).** A race or scoreboard that shows the fly alone meets the layout and fails the claim, so the page and its exporter refuse a fly lane or row without the counters beside it, and refuse any row whose role is not floor, ceiling, reference or under test. The brain panel shows what the learner did each step, so a short brain is an error, not a quiet blank.

## Invariants
- Reads one schema (`dashboard-v0`); anything it cannot honor is shown as an error, never silently replaced.
- No external CDN or network beyond local sample files: the page must render offline during video capture.
- Every lane, row and panel carries a claim tag. Feature names and scores are never shown as notes.
- Sample data under `dashboard/sample/` is synthetic.

## Demo page (`demo.html`): two coding runs side by side

A second page, independent of `index.html`: it replays `sample/<replay>.json` (schema `demo-replay-v1`, `sample/demo-replay.schema.json`) and shows `sample/demo-headlines.json` (`demo-headlines-v1`) as the results strip. URL options: `?replay=<name>&autoplay=0&speed=0.5|1|2&step=N&hook=0`. `tests/dashboard/test_demo_contract.py` checks the samples against the schemas; `demo.js` refuses the cross-field breaks a schema cannot state.

**Violation prevented: Paper Tiger.** The comparison only means something when the floor is really a floor and each decision is shown under the unit that made it. So the plain run must have `adapter: null` and no note, classifier or picker on any step; only `classifier` (who: "logistic classifier") carries speak / stay quiet; `picker` (who: "our network") names an adapter and has no speak field at all; totals must equal the sums of the steps; a fly headline row needs counters directly beside it.

**What the Route A and Route B runners must emit** (one file per task pair; emitters not built yet). `runs` holds exactly two entries, `plain` then `personal`, on the same task id, each with `subtitle` (one line shown under the run title, e.g. "Glimmer, lesson in the prompt (pilot), no adapter") and `role` (plain: floor, personal: under test) and `status: "measured"` for a real run. Per mini-SWE-agent step:
- `action`: a short label of what the step did, at most 12 words, written from the public task (never the model's command text, never a private session); `outcome`: progress, failed, solved or gave up.
- `tokens_in` and `tokens_out` from the model's usage for that call; `wall_s` from the runner's step timer.
- `mistake_tag`: `repeated` when the miner's signals match a failure already seen earlier in this run or in the lessons the personal arm was trained on, `new` for a first failure, else `none`; `wasted`: the step's work was later thrown away (reverted edit, timed-out run).
- `note`: the delivered note as `what`, `resolved`, `check` (each at most 12 words; `sample/` JSON passes QG-SEC-04), with `source` "classifier fired" (Route A: the service's event log shows a note delivered) or "Glimmer recalled" (Route B: the adapter's own output restated a lesson; tagged by the runner, not guessed by the page). A third source, "lesson in prompt (pilot)", marks the prompt pilot: the lesson sat in the task prompt, no classifier and no adapter ran (`scripts/routea/build_pilot_replay.py` emits `sample/pilot-sqlglot-<n>.json` from real trajectories, `status: "measured"`; its tags are heuristics: `repeated` = the same normalized command run again with no source edit in between (so a failing command re-run unchanged is included), or most (half or more) of a line range of a file already read read again; `new` = first failure of a command; `wasted` = a `repeated` step; the result comes from the grader rows (`resolved`) and the emitter fails when the trajectory disagrees; a file write (including `cat > path`) resets the repeat memory for commands that mention that file; each run also carries `shown_run`, `runs_solved`, `runs_total` (the arm's full record on the task, shown on the page); plain vs lesson run provenance is in the PR).
- `classifier`: the logistic classifier's decision from the service event log for that step, with a one-line `reason`; `picker`: only on steps where the adapter picker ran.
- `totals`: computed from the steps by the emitter, never typed by hand.
`demo-headlines.json` is copied from `results/*.json` and names its source file and commit per headline.

## Commands
Open `dashboard/index.html` through a local static server; `cd dashboard && npm ci` once per worktree (pinned eslint and html-validate, local only), then `scripts/gates/check_js.sh` (QG-FE-01), `uv run python scripts/gates/check_cdn.py` (QG-FE-02) and `scripts/gates/check_html.sh` (QG-FE-03, advisory).

## Review focus
Is the counters row still beside the fly row? Does any new element fetch from the network?

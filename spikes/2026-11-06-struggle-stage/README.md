# Spike: struggle stage mockup (2026-11-06)

Throwaway probe behind plan Tasks 2 and 9 (`docs/superpowers/plans/2026-11-06-harness-neutral-mining-curation.md`).
Nothing in `src/` imports it. No data is kept here: the scripts read a local, git-ignored copy of the
nebius OpenHands sqlglot traces and write `data.json` / `data.js` outside the repo.

- `measure.py`: how often failed-command and rework groups recur across sessions and tasks (counts only).
- `resolutions.py`: how failed-command lessons were "resolved" (real edit, re-spelled pass, never passed).
- `themes.py`: themes from task text intersected with the codebase's own vocabulary; eight struggle patterns.
- `build.py`: per-session facts (themes, patterns, turns lost, outcomes), traps with their sessions, session strips.
  Builds lessons one session at a time: 35 s for 2,678 sessions, against about 5 minutes over the whole history.
- `dash2-template.html` + `click.js`: the Pain points stage in the dashboard's theme; one selection
  (theme, pattern) scopes every panel. Needs `dashboard.css` from `src/symbiont/service/static/` and `data.js`
  (`window.D = <data.json>`) beside it, served over http.

Run (from the repo root, with the traces at <traces>):

    uv run python spikes/2026-11-06-struggle-stage/build.py <traces>/sqlglot.jsonl <out>/data.json

`build.py` expects a `data.json` already written by `prep.py` (same arguments plus the task metadata file); the
mockup's Files tab reads `heat`, `months` and `sessions_per_month` from it.

# dashboard: static replay page

See root CLAUDE.md for the repo rules. This file covers `dashboard/`.

**Purpose.** One static HTML/JS page that replays `results/*.json` and `runs/*/events.jsonl` as lanes, a scoreboard and a brain panel, for the video and the judges.

**Violation prevented: Paper Tiger (and Black Box).** A race or scoreboard that shows the fly alone meets the layout and fails the claim, so the page and its exporter refuse a fly lane or row without the counters beside it, and refuse any row whose role is not floor, ceiling, reference or under test. The brain panel shows what the learner did each step, so a short brain is an error, not a quiet blank.

## Invariants
- Reads one schema (`dashboard-v0`); anything it cannot honor is shown as an error, never silently replaced.
- No external CDN or network beyond local sample files: the page must render offline during video capture.
- Every lane, row and panel carries a claim tag. Feature names and scores are never shown as notes.
- Sample data under `dashboard/sample/` is synthetic.

## Commands
Open `dashboard/index.html` through a local static server; `cd dashboard && npm ci` once per worktree (pinned eslint and html-validate, local only), then `scripts/gates/check_js.sh` (QG-FE-01), `uv run python scripts/gates/check_cdn.py` (QG-FE-02) and `scripts/gates/check_html.sh` (QG-FE-03, advisory).

## Review focus
Is the counters row still beside the fly row? Does any new element fetch from the network?

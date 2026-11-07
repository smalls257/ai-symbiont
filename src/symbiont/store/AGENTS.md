# store: lessons and source pointers, never raw history

See root CLAUDE.md for the repo rules. This file covers `src/symbiont/store/`.

**Purpose.** SQLite store of mined lessons and of where each project's history lives (`local.py`); mining that re-reads those logs through the readers (`mining.py`); the two training exports (`training.py`); the blast-radius reference scan (`references.py`).

**Violations prevented: Silent Fallback at the privacy and hold-out boundaries, and Infected Core by copied history.** Memory is the personal model's weights (owner decision 2026-10-28), so no record row is ever persisted: logs are re-read from where the harness wrote them each time mining runs, and dropped after. A store that quietly filtered private lessons would make a privacy bug look like "no history", and one that kept a scored task's lesson would let it train a scored model, so both guards raise.

## Invariants
- **No raw history is stored.** Tables: `sources` (project, reader, path pointers), `lessons` (each with a bounded quote, resolution steps, `remote_safe`, source ids and task ids) and `trained` (lesson ids and export ids, no text). Nothing else.
- Mining screens before it stores (`MiningRules.screen`, from `symbiont settings mining min_sessions N`): `save_mined` replaces the lessons and, in the same transaction, the `held_back` (counts per reason), `mining_settings` (the min_sessions the run used), `struggle` (signature, sessions, occurrences) and `churn` (file, session id, edits) tables. They hold counts and names, never record text.
- Hold-out is checked at mining time (`remine`, via `records.holdout.refuse_held_out`) and again on the write path: `mined.save` requires `held_out_tasks` and refuses a lesson whose task ids are held out. A refused log is not registered. An id in neither spelling raises `UnrecognisedTaskIdError`.
- A registered log that is missing or unparseable raises naming the file; mining never skips it.
- `remote_view(consent)` raises `RemotePrivacyViolationError` when any lesson of the project may not reach a remote model; it never filters, and it returns lessons with credentials scrubbed (`miner.secrets`). Without the user's own-history consent (`store/consent.py`, `symbiont consent give|withdraw|show`, default withheld) every private lesson raises. With it, a lesson whose private records are all the user's own sessions (`records.privacy.is_own_history`: `private-sessions`, `live-*`) is allowed; SWE-chat and every other third-party private dataset still raises, and a private lesson naming no dataset counts as third-party.
- Two exports, two names: `lessons_for_memory_model` (Route A, remote-reachable, through `remote_view(consent)`) and `lessons_for_personal_model` (Route B, local, all lessons). No flag chooses between them.
- `forget_trained(project, manifest_path, exported=...)` deletes exactly the exported lessons, after writing a manifest (export id, lesson ids, source session ids, task ids, counts; no text). It never overwrites a manifest and deletes nothing if the write fails. The memory-model export skips lessons already trained on. `eval.training_manifest` checks it against the hold-out.
- `ignored.py` keeps the patterns the developer set aside (`ignored` table: project, signal, key, label; the label is the title when ignored). `Store.lessons` leaves every ignored signature out, so notes, reviews and the dashboard all see it gone through that one read; mining counts a lesson-grade ignored group as IGNORED (`store.mining.with_ignored`) but still saves its lessons, so restoring brings them back with no re-mining, even after a re-mine.
- `triage.py` keeps the developer's review status per failure group (`triage` table: project, group_key, state, return_rule, after_sessions, changed_on, taught_on). Developer-owned like `ignored`, so it is NOT in `REPLACED_TABLES`: a re-mine keeps it. `group_key` is the group's opaque fingerprint, kept as text.
- `incident_rows.py` keeps one JSON card per failed command or correction (`incidents` table), built from ALL mined lessons (kept, held and struggle) so the Inbox shows unfixed failures and noise. In `REPLACED_TABLES`: a re-mine replaces them. Read with `store.mined.incidents(project)`.
- `contexts.py` keeps the developer's own words per lesson in the `contexts` table (their text, not record text; keyed by lesson id so a re-mining keeps them).
- `session_summaries.py` keeps the session model's summaries (`session_summaries`: goal, outcome, friction, noise) and the topic map (`topics`: topics, frictions, correction groups). Like ignored patterns they are developer-owned and NOT in `REPLACED_TABLES`, so a re-mine keeps them; `read_facts` and `read_strips` show a summary's goal as the session title.
- `repos.py` keeps the per-repository answer (allowed, declined, never asked), silenced kinds of trouble and the one-time nightly announcement in `repos.json`, rewritten atomically. A missing answer is never read as yes; a malformed file raises. `Store.forget_trouble` deletes a kind of trouble's lessons for `symbiont forget`.
- Periphery: tests touch the disk and carry `@pytest.mark.periphery`.

## Imports
- May import: `records`, `miner`, `readers`. Imported by: service, eval, cli, scripts. Never by the pure core.

## Commands
`uv run pytest tests/store -q`

## Review focus
Does any new table or column hold record text beyond a lesson's bounded quote? Does any new read path bypass `remote_view()` for remote-bound use? Is any new write path missing the mining-time hold-out check?

# scripts: periphery tooling

See root CLAUDE.md for the repo rules. This file covers `scripts/`.

**Purpose.** `calibration/` (task pool and calibration runs), `swev/` (SWE-bench Verified Django run: task pick, per-task-image runner, official-test scorer, lesson selection), `datasets/` (dataset exporters), `gates/` (quality-gate checks), `hooks/` (tracked git hooks), `publish/` (the pre-publication export check), `routea/` (the lesson-capacity probe: lessons from public trajectories, MLX LoRA runs on the laptop, deterministic scoring; and Route A end to end: `fit_warner.py` fits the logistic warner on the public pool, `train_memory.py` trains the memory model's LoRA through the shared `train_lora.sh` and then forgets the lessons, `serve_memory.sh` serves it on loopback, `demo.sh` runs the loop on synthetic sessions; the MLX half runs in a venv outside the repo, weights and adapters stay outside it), `routeb/` (the personal Glimmer LoRA: the same lessons as Glimmer chat rows built on the laptop, then `run_routeb.sh` on the Strix trains bf16 adapters, converts them to GGUF and answers every arm; only `build_sets.py` and `cards.py` run in the repo env, the rest in the Strix venv; the GPU half runs only inside `ops/gpu_run.sh`; `build_sqlglot_set.py` builds the per-repo sqlglot adapter's set from Glimmer's own public calibration runs, three-part lessons plus situation-to-action rows, and stops on any evaluation task's gold line; `check_sqlglot_set.py` counts its tokens on the Strix; `nightly.py` is the overnight job, per repo: mine, export the untrained lessons, build rows (`symbiont.routeb.lesson_rows`), upload, train through `ops/gpu_run.sh`, install the personal name in the router preset (`glimmer_preset.py`), verify, forget; it reads `~/.config/symbiont/nightly.toml` (`nightly.example.toml`) and drives the host half, `ops/routeb_nightly_host.sh`, over ssh), `install-hooks.sh`. `routeb/general_*.py` and `routeb/build_general_lessons.py` build the general sqlglot lessons (habits, repo knowledge, implementation) from non-evaluation history only; the evaluation ids come from `results/general-split.json`, declared first by `routeb/declare_general_split.py`.

**Violation prevented: Infected Core.** Anything that reads a dataset, shells out or talks to a machine lives here, so `src/` stays pure and nothing in `src/` imports from `scripts/`.

## Invariants
- No raw dataset rows or transcripts are written into tracked paths; outputs go to gitignored `data/` or publish counts only.
- Hosts, addresses and user names come from the environment, never committed. The owner's own identifiers live in `~/.config/symbiont/private-terms.txt`, outside every worktree; `gates/check_private_terms.py` (QG-SEC-05) fails closed without it and warns when the file is readable by group or others (`chmod 600`).
- Sensitive-data gates, earliest stage first: edit-time text scan in `.claude/hooks/guard_paths.sh` (QG-SEC-06); at commit `check_paths.sh` (names read NUL-delimited and case-insensitively, size, binaries, `results/` is `.json` only), `check_results_content.py` (counts and labels only), `check_secrets.sh staged`, `check_private_terms.py staged`; at push the history scan; before the first public push `publish/check_export.sh`, which re-runs them on `git archive HEAD`.
- Scripts that fetch public datasets may use the network; code under `src/` may not: it calls `symbiont.egress`.
- Ruling (2026-10-28): Route B's overnight job is `scripts/routeb/nightly.py`, not a `symbiont nightly` subcommand. It drives the training host over ssh and scp, which `src/` may not launch (semgrep `sym-network-subprocess`), and a subcommand that shelled out to a script would be the same second network client in disguise and would break for an installed `symbiont` with no checkout. The pure part, lessons to training rows, is in `src/symbiont/routeb/lesson_rows.py`; the script imports `symbiont`, never the reverse.
- Gate scripts (`gates/`): anchored to the git root, fail closed (missing tool or config exits non-zero), one definition per gate, changed files only in phase 1, waiver files delete-only.
- Spark-bound code receives `Store.spark_view()`; one price table (`eval/budget.py`).
- Python here is held to the same size, nesting and naming caps as `src/`; gate scripts obey the caps they enforce.
- A fresh worktree has no `.venv`: every gate fails with `run: uv sync --group dev` until you run it. The semgrep registry snapshot (QG-SAST-01) is gitignored: run `scripts/gates/fetch_semgrep_packs.sh` once per checkout (network). The frontend gates need `cd dashboard && npm ci` before they can judge a changed dashboard file.
- Pre-commit is fast (changed-file checks plus the unit tests of touched packages); the whole suite, the `run.sh` tests and the history scan run at pre-push.
- `publish/` is a gate directory like `gates/`: protected, owner-edited, `GATE-CHANGE` trailer.
- Gate files are owner-edited; a change needs a `GATE-CHANGE: <reason>` commit trailer (QG-GATE-01), in that commit's own message.

## Environment
Names only, set in your shell; `env.example` shows placeholder shapes. Unset means the script exits with a message naming the variable.
- `SYMBIONT_GLIMMER_URL`: Glimmer endpoint, read by `calibration/run_calibration.py`. Start the staged driver with `python scripts/calibration/launch.py <workdir>`, not `staged.py`: `launch.py` checks the variable before anything loads.
- `SYMBIONT_PERSONAL_GLIMMER_URL`, `SYMBIONT_PERSONAL_GLIMMER_MODEL`: the personal-Glimmer endpoint, read by `swev/swev_run.py` for the personal arm only; start with `python scripts/swev/swev_launch.py`, which checks every listed arm's variables first.
- `SYMBIONT_DESKTOP_SSH`, `SYMBIONT_DESKTOP_WORKDIR`: desktop login and its work dir, read by `calibration/sync_results.sh`.
- `SYMBIONT_DRIVER_PATTERN`: test-only override of the driver probe pattern in `calibration/sync_results.sh` (default `launch.py|staged.py`).

## Commands
`scripts/gates/run.sh fast`, `scripts/gates/run.sh full`, `scripts/gates/mutation.sh` (QG-TST-05, minutes, release only), `scripts/publish/check_export.sh`, `uv run python scripts/gates/measure_baseline.py --write`

## Review focus
Does a script hide a machine name, a token path or a `|| true` after a check? Does a new data path or result field skip `check_paths.sh` and `check_results_content.py`?

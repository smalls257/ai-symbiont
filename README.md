<h1>
  <img alt="ai-symbiont" src="docs/brand/logo-light.svg#gh-light-mode-only" width="360">
  <img alt="ai-symbiont" src="docs/brand/logo-dark.svg#gh-dark-mode-only" width="360">
</h1>

[![Llama 3.2 1B checker adapters on Hugging Face](https://img.shields.io/badge/%F0%9F%A4%97%20model-Llama--3.2--1B--symbiont--judge--adapters-yellow)](https://huggingface.co/smalls257/Llama-3.2-1B-symbiont-judge-adapters)

**Frontier models know everything except your codebase. ai-symbiont teaches it.**

You corrected your coding agent last week. Today it makes the same mistake again. ai-symbiont is a plugin for Meta's Muse Code. It learns from your agent's past sessions, your corrections and your team's code reviews, on your own machine, and gives the agent one plain sentence right before it repeats a mistake.

**Headline result:** on a real open-source project (sqlglot), Muse Spark broke a rule that only the maintainers' code reviews state in **7 of 10** runs without symbiont and **0 of 10** with it. Same task, every run passed the tests; p = 0.003, pre-registered. [measured] [pre-registered]

[![Watch the 3-minute demo on YouTube](https://img.youtube.com/vi/sIKmLvDYZ-4/maxresdefault.jpg)](https://youtu.be/sIKmLvDYZ-4)

**▶ [Watch the 3-minute demo](https://youtu.be/sIKmLvDYZ-4)** · Project page with recordings: <https://smalls257.github.io/ai-symbiont/> · Paper: <https://smalls257.github.io/ai-symbiont/paper.html>

### Try it

- **In Muse Code, one command onboards a repository** (allow, learn from past sessions, find your corrections, download and train the checker):
  ```bash
  uv tool install 'ai-symbiont[nightly] @ git+https://github.com/smalls257/ai-symbiont'
  muse plugins marketplace add ai-symbiont https://github.com/smalls257/ai-symbiont
  muse plugins install symbiont@ai-symbiont && muse plugins approve symbiont
  muse            # then type: /symbiont onboard
  ```
- **A live Muse Code session in Docker** (needs a Meta API key; about a minute to start): `docker build -t ai-symbiont . && docker run -it --rm -e META_API_KEY=... ai-symbiont live`
- **No key, nothing to install:** the interactive demo on the [project page](https://smalls257.github.io/ai-symbiont/demo/), or `docker run --rm ai-symbiont demo`.

### Meta's models, and the job each one does

| Piece | Its job here | Without it |
|---|---|---|
| **Muse Code** | The host. symbiont is a Muse Code plugin: hooks bring notes into the agent's loop, MCP tools run `/symbiont onboard`, `status` and `why`. | The notes have no way into the agent's work. |
| **Muse Spark 1.3** (`api.meta.ai`) | The coding agent in every measured run. It also reads the candidate lessons and corrections and keeps the ones that hold; symbiont makes no model calls of its own. | No agent, and nothing decides which lessons are worth keeping. |
| **Llama 3.2 1B Instruct** (open weights) | The checker. A LoRA trained on each repository's own history, on your machine, must agree before any note is shown. Adapters on [Hugging Face](https://huggingface.co/smalls257/Llama-3.2-1B-symbiont-judge-adapters). | In the precision test, plain similarity search showed 9 wrong notes; with the checker, 0 of 501. |
| **Muse Glimmer 30B** (open weights) | An early test and my next step: see [Open problem](#open-problem-lessons-inside-the-models-weights). | Not used at runtime. |

**Hackathon facts:** Indie Developer track · Push the Frontier · built from scratch during the hackathon (Oct 26 – Nov 4, 2026), no prior code · bonus categories targeted: Best Build on Meta Open Weight Models (Llama 3.2 1B checker), Best Agentic Use-Case, Best Creative Build.

## Results at a glance

Every model run below used Muse Spark, Meta's model.

**Coding**

- **A rule only the maintainers' reviews state (real public repo).** In sqlglot, the rule "don't `.copy()` in generator code; the generator copies the whole tree up front" appears in no doc or code, only in maintainer reviews of earlier pull requests. symbiont learned it from those reviews and showed the agent the reviewer's own words. On the same real task (PR #7433): a forbidden `.copy()` in 7 of 10 runs without symbiont, 0 of 10 with it (p = 0.003); all 20 runs passed the task's tests. One repository, one rule, one task, one model; I wrote the tests because the PR had none. [measured] [pre-registered]
- **Corrected once, never repeated.** The user states three rules for a repository once. Over 18 chances across 8 new tasks, the agent broke a rule 16 times without symbiont and 0 times with it. A synthetic, designed task, one model, one run per task. [measured] [pre-registered]
- **Precision.** 0 wrong notes in 501 shown, on 89 open-source projects it had never seen; a plain similarity search got 9 wrong. The test bugs were planted, not made by real developers. [measured] [pre-registered]
- **Nightly training.** Untrained, the checker blocked every note on code it had never seen. After one night of training on the project's own history it approved 61% of repeats, and 97.8% of what it approved was right. [measured] [pre-registered]

**The same loop, other worlds**

- **Home robot (Meta Habitat), set the table:** 4 of 5 new episodes with symbiont's notes, 0 of 5 without; giving the robot every lesson up front also reached 4 of 5, so the win here is the learned lessons, not their timing, in one fixed home. Details in `docs/research/2026-11-03-habitat-results.md`. [measured] [pre-registered]
- **House rules:** 30 violations across 6 episodes without the owner's corrections, 0 with them (corrections scripted for the demo). [measured] [pre-registered]
- **Freedoom, via ViZDoom:** Muse Spark proposed six rules for itself from its failed games; symbiont's automatic test, fixed before any test game, kept one. Across 240 new games it raised the game score (0 to 1) by 0.16. [measured] [pre-registered]

## Open problem: lessons inside the model's weights

- **Muse Glimmer 30B with lessons in its prompt:** in an early test it solved 6 coding tasks with symbiont's lessons against 2 without (Tier 1 5 vs 2, Tier 2 1 vs 0, clean runs only; one lesson run per task, so counts, not rates; `results/lesson-pilot.json`). Exploratory. [measured]
- **Lessons trained into weights are remembered:** one LoRA adapter on Llama 3.2 1B holding 100 lessons recalled 88% of them (65% on reworded questions), against 25% with all 100 in the prompt (`results/lesson-capacity.json`). Exploratory. [measured]
- **Using them is the open part:** my first coding LoRA on Glimmer (Route B, builders in `src/symbiont/routeb` and `scripts/routeb`) scored 0.054 below plain Glimmer, interval [-0.108, -0.014], stopped early at 37 of 60 blocks (`results/core-v3-stopped-final.json`). A retrain with a shorter context is in development. [measured]

Pre-registered evaluations, with the result file, prereg and research note behind each number: [Benchmarks and evaluation](benchmarks/README.md).

## Quickstart

Install the command, then the plugin for your harness.

```bash
uv tool install 'ai-symbiont[nightly] @ git+https://github.com/smalls257/ai-symbiont'
```

Claude Code:

```text
/plugin marketplace add https://github.com/smalls257/ai-symbiont
/plugin install symbiont@ai-symbiont
```

Muse Code:

```bash
muse plugins marketplace add ai-symbiont https://github.com/smalls257/ai-symbiont
muse plugins install symbiont@ai-symbiont
muse plugins approve symbiont
```

Start a session in a repository. The first time, symbiont says what it does and asks. Answer with
`/symbiont allow` (or `/symbiont decline`), then `/symbiont mine` to learn from this
repository's past Claude Code and Muse Code sessions (it finds both on its own, and opens the dashboard so you can watch the progress; `--no-open` skips that). `/symbiont` shows status, explains the last note, mutes it
or forgets its lessons. Its actions are MCP tools of the symbiont server (`symbiont_allow`,
`symbiont_mine`, `symbiont_status` and the rest), so they work where the harness shell is sandboxed
(Muse Code); the shell forms (`symbiont repo allow`, `symbiont repo mine`)
remain for a harness without MCP.

Try it without a key: `docker build -t ai-symbiont . && docker run --rm ai-symbiont demo`. It replays a synthetic billing-ledger session offline (onboarding note, `symbiont repo allow` and `repo mine`, house rules, a recall note, `symbiont why`) and needs no API key and no network. Locally: `scripts/demo/run.sh`. The interactive demo on the landing page needs nothing installed: <https://smalls257.github.io/ai-symbiont/>. Only runs that call Muse Spark need `META_API_KEY` (see `env.example`).

Try it live in a real Muse Code session (needs a Meta API key; Muse is downloaded when the container starts, about a minute):

```bash
docker build -t ai-symbiont . && docker run -it --rm -e META_API_KEY=... ai-symbiont live
```

It opens Muse on the synthetic ledger with the plugin installed and its hand-written history mined, and prints a short "try this" card. symbiont's notes show up as `symbiont:` lines. The nightly learner and Llama training are skipped (too slow on a CPU).

Optional: a container for running the test suite and the command-line tool (not the harness
plugins). `symbiont serve` binds 127.0.0.1 inside the container, so the service is not reachable
from the host; there is no `--host` option and this image does not change that.

```bash
docker build -t ai-symbiont .
docker run --rm ai-symbiont uv run pytest -q \
  --ignore=tests/dashboard/test_mining_view.py \
  --ignore=tests/gates/test_check_export.py \
  --ignore=tests/gates/test_claude_hooks.py \
  --ignore=tests/gates/test_frontend_gates.py \
  --ignore=tests/gates/test_gitleaks_rules.py \
  --ignore=tests/gates/test_run_script.py \
  --ignore=tests/gates/test_shell_gates.py \
  --ignore=tests/ops/test_gpu_run.py \
  --ignore=tests/scripts/test_sync_results_probe.py     # the tests that can run here
docker run --rm ai-symbiont symbiont --help      # the command line
```

The command above ignores nine test modules that need tools the image does not carry: gitleaks and the other quality-gate tools (`tests/gates/` modules for the secrets rules, the export check, the hooks, the shell gates and `run.sh`), Node (the JavaScript gate and the dashboard mining view), and the docker and ssh helpers for the GPU host (`tests/ops/test_gpu_run.py`, `tests/scripts/test_sync_results_probe.py`). In the container the rest gives 2703 passed and 0 failed [measured]. Without the `--ignore` flags the same image gives 2867 passed and 54 failed or errored [measured], all from those modules. Run the full suite on your machine with `uv sync --group dev && uv run pytest -q`.


## Learn from your team's PR reviews

symbiont asks once whether to learn from this repository's recent pull-request reviews and CI
failures; `/symbiont learn-from-prs` does it any time. Your session's model reads GitHub with your own
`gh` access and saves a few short lessons, each linked to its pull request on the dashboard.
symbiont itself makes no network call and stores only those lessons and links, locally. Details in
`docs/product/plugin.md`.

## Nightly training

`symbiont nightly` trains a small judge (Llama 3.2 1B with a LoRA adapter) on this repository's
lessons, on your own machine, so that recalls and notes get stricter about when a stored lesson
applies. It is the recipe of plug round 4's nightly arm: a fixed base (the general judge), all of
the repository's lessons so far, 15% habit replay [established], trained fresh each night and never
stacked on the last one. One difference, tagged `[hypothesis]`: the measured arm used Spark to invent
situations and labels, and this command makes no network call, so it rewords each lesson's
situation with a fixed list of templates instead. Its numbers are not that arm's numbers.

```bash
symbiont nightly                      # this repository, now
symbiont nightly --project NAME       # another stored project
symbiont nightly schedule install     # every day at 03:00 (--at HH:MM to change it)
symbiont nightly schedule status      # is it scheduled, and when
symbiont nightly schedule remove
```

It runs locally and uploads nothing. It trains with mlx-lm on Apple Silicon and with torch on an
NVIDIA GPU; on any other machine it says so and stops, and it never trains on the CPU. It prints
each stage's seconds and the lesson count, writes the nightly record only after the trainer exits
0, and a failed night leaves the older record, which then reads as stale. With no lessons it says
so and exits 2; any other failure exits 1. `symbiont status` and the dashboard header show one of
three states: never trained, trained on N lessons at a time, or stale (the lessons changed since).
The schedule uses launchd on macOS (a user LaunchAgent), a tagged line in your crontab on Linux
and Task Scheduler on Windows; a Mac that is asleep at the set time runs the job when it wakes.

**Install it with the nightly extra.** A plain `uv tool install` carries neither the trainer nor
torch, and `symbiont nightly` then says so and exits non-zero. One command installs everything the
nightly needs, with no repository checkout and no second Python:

```bash
uv tool install 'ai-symbiont[nightly] @ git+https://github.com/smalls257/ai-symbiont'
```

The `nightly` extra is mlx-lm on an Apple Silicon Mac (an environment marker), plus torch, peft and
transformers everywhere (the judge server and the kit merge run on torch; a Mac uses mps). The
trainer, the kit merge and the judge server all default to the Python that `symbiont` itself runs
on, so `--trainer-python` and `--judge-python` are only for a setup with separate environments. On
Linux and Windows the trainer needs a CUDA build of torch (PyPI's Windows wheel is CPU-only, so install
one from pytorch.org into the tool environment first). The scripts ship in the package and unpack to
`~/.symbiont/routea`; `SYMBIONT_ROUTEA_DIR` overrides them for development.

**One command.** `/symbiont onboard` allows the repository, mines it, saves your corrections and starts the first training; it needs nothing else: on the first run it downloads the model and kit itself (see Finding the downloads).

**From your coding agent.** `/symbiont nightly` (the `symbiont_nightly` tool, `symbiont nightly start`
in a shell) sets up if needed, trains in a detached process and returns within a minute; training
takes 1-4 minutes. `/symbiont status` then shows `training job: running`, `done on N lessons at T` or
`failed: <reason>`, and the checker starts or reloads when the job is done. With no kit and no folders
given it fails with the steps below; once a kit exists it needs no arguments.

**What it needs.** A judge kit folder (`--kit`, `$SYMBIONT_JUDGE_KIT`, else `~/.symbiont/judge-kit`)
holding `base/` (the general judge: Llama 3.2 1B with the round-4 general adapter merged in),
`general-rows.jsonl` and `habits.jsonl`; a Python with `mlx-lm` (`--trainer-python`, default: the install's own) or with CUDA
torch, transformers and peft; and the judge server, which ships inside the package
(`routea_bundle/`; a developer can point `SYMBIONT_ROUTEA_DIR` at a `scripts/routea` instead), run on
a Python with torch (`--judge-python`). After a night the command makes the judge server serve the new adapter: it hot-swaps a running server
or starts one (detached, log beside the adapter) and waits until it answers, and it records how to
start it again in the nightly record. Nothing else is needed: the symbiont service that the hooks
start on their own reads `<data-dir>/nightly` on every recall, so once a repository has a record, its
recalls are checked (the agree rule with that repository's judge) with no flags. If the checker is
down, for example after a reboot, the recall says `symbiont checker offline`, starts the server again
from the record and asks you to retry in a minute; it never falls back to the ranker alone. With no
record yet nothing changes (the ranker answers) and `symbiont status` and the dashboard say
`checker not trained yet; run symbiont nightly`. `symbiont why` names the checker that agreed to the
last note (its model, how many lessons it was trained on and when), never a score.

**What the checker gates.** Two kinds of note are recalls of a stored lesson, and with a trained
checker both go through the agree rule: the answer to a `recall` question, and the hook-time note
after a failed command ("Last time, `X` failed with E; it was fixed when you..."). For the hook
note the service describes the failure to the judge the way the lessons were described in training
(the command, the repository, the file, the last line of output), and if the judge disagrees there
is no note. The judge gets 0.35 s of the hook's 0.6 s budget [hypothesis]: if it is down you see `symbiont
checker offline` (and it is started again); if it is running but slower you see `symbiont checker
slow` and no note for that failure. Either way the failure is checked again next time it repeats. With the judge warm, a hook that reaches it takes about 0.14 s end to end on an Apple M-series Mac [measured]. The checker is strict by design: on 20 synthetic repeats it approved 1 [measured], and the rest got no note.
House rules, file rules and PR rulings are never gated: they are rules you or your team wrote, not
recalls. With no nightly record nothing is gated.

**Finding the downloads.** With no `base` or `kit` given, `symbiont nightly` uses a kit it already built, else looks for the Llama folder in `~/.symbiont/models/llama-3.2-1b-instruct`, then the Hugging Face cache (`$HF_HOME/hub` or `~/.cache/huggingface/hub`, newest snapshot); the kit in `~/.symbiont/models/nightly-kit`, then the cache's `nightly-kit/`. If nothing is found, the background job downloads them itself first (about 2.5 GB from Hugging Face, public files and no login: the base is the ungated `unsloth/Llama-3.2-1B-Instruct` copy of Meta's weights, and setup still checks its shape and chat template), into `~/.symbiont/models`; `/symbiont status` shows `downloading model 1.1 of 2.5 GB`. Doing it by hand also works: `hf auth login`, `hf download meta-llama/Llama-3.2-1B-Instruct`, `hf download ADAPTERS_REPO --include "nightly-kit/*"` (ADAPTERS_REPO as above).

**Building the kit (once).** Meta's license does not let me ship Llama weights, so you fetch the base
yourself and `symbiont nightly setup` merges the small public kit into it on your machine. It makes
no network call.

```bash
# accept Meta's license on https://huggingface.co/meta-llama/Llama-3.2-1B-Instruct, then:
huggingface-cli login
huggingface-cli download meta-llama/Llama-3.2-1B-Instruct --local-dir ./llama-3.2-1b-instruct   # about 2.5 GB
# the kit: the nightly-kit/ folder of https://huggingface.co/smalls257/Llama-3.2-1B-symbiont-judge-adapters
huggingface-cli download ADAPTERS_REPO --include 'nightly-kit/*' --local-dir ./kit   # about 100 MB; ADAPTERS_REPO is the path of that URL
symbiont nightly setup --base ./llama-3.2-1b-instruct --kit-files ./kit/nightly-kit   # or: /symbiont nightly, with base and kit set to those folders
```

Setup checks that the folder is Llama 3.2 1B Instruct (config, tokenizer, weights, chat template)
and that every kit file matches its pinned SHA-256, merges `judge-s0` and then `general` into the
base, and writes `base/`, `general-rows.jsonl` and `habits.jsonl` into the kit folder. A wrong or
missing file stops it with the exact download command. The kit's two row files are built from public
trajectories and templates, with no text from any hosted model; the Hugging Face folder's README
records how that was checked. Built with Llama; Llama 3.2 is under the Llama 3.2 Community License.

**How long.** Time grows with the number of lessons. Each distinct lesson becomes about 22 training rows with the replay mixed in [measured].
The trainer makes three passes over them.
On an Apple M-series Mac (48 GB) with 20 synthetic lessons (439 rows, 329 updates), two nights took 225 s and 221 s [measured].
Nearly all of that was training; reading lessons, building rows, converting and installing the adapter and writing the record took under a second together [measured].
Both nights ran while other jobs kept the machine's load average between 7 and 25, so an idle laptop should do better [hypothesis].
Run it overnight, not in a loop.

## Reproduce it

`REPRODUCE.md` has three tiers: a one-command demo (about a second, no model), a check that recomputes the headline numbers from committed files (about 10 seconds), and the rebuild of the code-fix study's data from a pinned public dataset.

## Privacy

Everything stays on this computer. The service listens on 127.0.0.1 only, the lessons live in
`~/.symbiont`, and nothing is stored for a repository until you say yes. Hook events are sent to
that local service and nowhere else. Notes quote a short excerpt of your own history back to your
own agent; they are never sent to a remote service by the plugin.

## Uninstall

Claude Code: `/plugin uninstall symbiont@ai-symbiont`. Muse Code: `muse plugins remove symbiont`.
Then `uv tool uninstall ai-symbiont` and delete `~/.symbiont` (the lessons, the answers per
repository and the logs).

The design is in `docs/product/plugin.md`.

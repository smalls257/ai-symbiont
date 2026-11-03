# ai-symbiont

ai-symbiont reads your coding-agent history for pain points (a file reworked three times, a command
that failed the same way twice, a correction you had to make) and gives your agent a short warning
in plain prose before it repeats one. It runs on your computer.

## Install

Install the command, then the plugin for your harness.

```bash
uv tool install git+https://github.com/smalls257/ai-symbiont
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
`symbiont repo allow` (or `symbiont repo decline`), then `symbiont repo mine` to learn from this
repository's past Claude Code and Muse Code sessions (it finds both on its own, and opens the dashboard so you can watch the progress; `--no-open` skips that). `/symbiont` shows status, explains the last note, mutes it
or forgets its lessons.

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

**What it needs.** A judge kit folder (`--kit`, `$SYMBIONT_JUDGE_KIT`, else `~/.symbiont/judge-kit`)
holding `base/` (the general judge: Llama 3.2 1B with the round-4 general adapter merged in),
`general-rows.jsonl` and `habits.jsonl`; a Python with `mlx-lm` (`--trainer-python`) or with CUDA
torch, transformers and peft; and the judge server, `scripts/routea/plug_judge_server.py`, run on
a Python with torch (`--judge-python`). After a night the command asks the running judge server to
load the new adapter, or prints the exact command to start it. A symbiont service started with
`--nightly-dir ~/.symbiont/nightly` (and `--judge-url`) reads the record on every recall, so it
needs no restart; one started without those options must be restarted with them.

**How long.** Time grows with the number of lessons. Each distinct lesson becomes about 22 training rows with the replay mixed in [measured].
The trainer makes three passes over them.
On an Apple M-series Mac (48 GB) with 20 synthetic lessons (439 rows, 329 updates), two nights took 225 s and 221 s [measured].
Nearly all of that was training; reading lessons, building rows, converting and installing the adapter and writing the record took under a second together [measured].
Both nights ran while other jobs kept the machine's load average between 7 and 25, so an idle laptop should do better [hypothesis].
Run it overnight, not in a loop.

## Reproduce it

`REPRODUCE.md` has three tiers: a one-command demo (about a second, no model), a check that recomputes our headline numbers from committed files (about 10 seconds), and the rebuild of the code-fix study's data from a pinned public dataset.

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

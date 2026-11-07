---
description: Show what symbiont is doing here, explain a note, silence it, forget a lesson, or answer for this repository
argument-hint: "[onboard | status | dashboard [inbox|topics|trends|struggle|context|replay] | settings | why | mute | forget | lessons | context | reflect | learn-from-prs | review | allow | decline | mine | nightly | uninstall]"
allowed-tools: Bash(symbiont:*), mcp__symbiont, mcp__plugin_symbiont_symbiont
---

You are running the `/symbiont` command. The argument is: $ARGUMENTS

Run exactly one action from this table, then tell the developer the result in one or two plain
sentences. Never invent output; if an action fails, quote its message.

**Use the symbiont tool when you have it** (the MCP tool in the Tool column; its name may carry a
server prefix). Some harnesses, Muse Code among them, run your shell in a sandbox that cannot
write symbiont's data folder, so the shell command fails there with "sandbox blocked"; the tool
runs in symbiont's own process and works. Only when you have no symbiont tool at all, run the
shell command in the last column instead. If the tool is there and fails, quote its message; do
not retry through the shell.

| Argument | Tool | Shell fallback | Meaning |
|---|---|---|---|
| empty or `status` | `symbiont_status` | `symbiont status` | whether symbiont is running, and what it knows about this repository |
| `why` | `symbiont_why` | `symbiont why` | why the last note fired, and what it rested on |
| `mute` | `symbiont_mute` | `symbiont mute` | stop notes about the kind of trouble the last note was about |
| `forget` | `symbiont_forget` | `symbiont forget` | delete the lessons behind the last note and keep them silenced (`lesson_id` / `--lesson` for one lesson) |
| `lessons` | `symbiont_lessons` | `symbiont lessons` | list the stored lessons for this repository with their ids |
| `context <id or last> <words>` | `symbiont_context` with `lesson`, `words` (`intentional`, `priority` low, normal or high) | `symbiont context add <id or last> "<words>"` (`--intentional`, `--priority low\|normal\|high`) | put the developer's own words in front of a lesson's note |
| `settings` | `symbiont_settings` | `symbiont settings show` | which histories the session's model may read when looking for corrections |
| `allow` | `symbiont_allow` | `symbiont repo allow` | switch symbiont on for this repository |
| `decline` | `symbiont_decline` | `symbiont repo decline` | keep symbiont off for this repository |
| `mine` | `symbiont_mine` | `symbiont repo mine` | learn from this repository's past agent sessions (needs `allow` first). It opens the dashboard unless the developer turned that off (`symbiont settings set open_dashboard_on_mine false`; shell: `--no-open` skips the browser) and returns the address with a progress summary; if the job is still running, say it carries on and give the address |
| `nightly` (normal path: no arguments; optionally `base=<folder> kit=<folder>`) | `symbiont_nightly` with no arguments; `base` and `kit` only when the developer gave them | `symbiont nightly start` (`--base <folder> --kit-files <folder>`) | train this repository's checker on its lessons, on this machine (nothing is uploaded). It builds the judge kit first if there is none, then trains in the background and returns within a minute with "training started; N lessons; check with `/symbiont status`"; training takes 1-4 minutes and `status` then shows `training job: running`, `done on N lessons at <time>` or `failed: <reason>`. With no arguments it finds the Llama folder and the nightly kit by itself (`~/.symbiont/models`, then the Hugging Face cache), reuses a kit it already built, and when it finds nothing it downloads both itself (about 2.5 GB, public files, no login) in the background job before training; `/symbiont status` then shows `training job: downloading model 1.1 of 2.5 GB`. If a download fails, quote the `failed:` reason; if it says the nightly packages are missing, give the developer the install command it quotes. Never retry through the shell when the tool answered |
| `onboard` | `symbiont_allow`, `symbiont_mine`, the correction tools, then `symbiont_nightly` (see below) | `symbiont repo allow`, `symbiont repo mine`, `symbiont nightly start` | set this repository up from nothing, in one command |
| `dashboard [view]` | `symbiont_dashboard` (pass `view`) | `symbiont dashboard [view] --open` | one page of this repository's dashboard. The views are `inbox` (the default: what needs a look first), `topics`, `trends`, `struggle`, `context` and `replay` (the 30-day replay and the measured results). Call `symbiont_dashboard` with the view the developer named (none means inbox), then tell the developer the address in your reply, and open it with `open <address>` on macOS, so they can open it even if no browser opened. If the tool says symbiont is offline, say so; there is no address to give |
| `learn-from-prs` | `symbiont_learn_from_prs`, then follow the steps it returns yourself with your own `gh` access | `symbiont learn-from-prs`, then the same | learn lessons from this repository's recent pull-request reviews and CI failures; symbiont reads nothing from GitHub, you save the lessons with `symbiont_add_lessons` (source_label like "from PR #412 review", source_url the PR address) |
| `review` | `symbiont_review_candidates`, then `symbiont_save_reviews` | no shell command | fetch the candidate pain points, which carry what the user asked, what the agent meant to do, how often it happened and how it ended; for each write a summary of two or three sentences (what the agent was trying to do, what went wrong, whether it was fixed, whether it is worth keeping as a lesson) and a verdict (mistake, expected or noise), then save them all with `symbiont_save_reviews` (`id`, `verdict`, `summary`, `rule_in_plain_words`, `title`). Repeat while `remaining` is above zero. Tell the developer how many you judged |
| `reflect` | no tool or command; do it yourself now | | answer "In one or two plain sentences each, what non-obvious thing about this repository would you tell a teammate before they work on this area next time? Name the files or areas. Only things that were not obvious from the docs." from the work done in this session, then call `symbiont_add_lessons` with `source_label` "from reflection" (kind `rule` or `mistake`, `files`, `applies_to`); say "nothing" and call no tool if there is nothing |

**`onboard`** runs these five steps in order and reports each in one plain line:

1. `symbiont_allow`: switch symbiont on for this repository.
2. `symbiont_mine`: learn from the past sessions; give the developer the dashboard address it returns.
3. Find corrections the same way as always: `symbiont_correction_candidates`, judge each item yourself, then `symbiont_save_corrections`.
4. `symbiont_nightly` with no `base` or `kit`. On a first run it downloads the model and kit itself (about 2.5 GB) before training; relay what it says. If it reports a failure, quote it and stop.
5. Say that the download (first run only) and training run in the background (training takes 1-4 minutes) and to check `/symbiont status`.

When the developer points you at notes, reports or lessons they keep, read what they point to, decide in your own words what is worth keeping, and call `symbiont_add_lessons`. When symbiont asks you to review pain points or look for corrections, call `symbiont_review_candidates` or `symbiont_correction_candidates`, judge each item yourself, and save with `symbiont_save_reviews` or `symbiont_save_corrections`. symbiont makes no model calls of its own.

For `uninstall`, run nothing. Tell the developer to remove the plugin with `/plugin uninstall
symbiont@ai-symbiont` in Claude Code, or `muse plugins remove symbiont` in Muse Code, and to remove
the command and its stored data with `uv tool uninstall ai-symbiont` and by deleting the folder
`~/.symbiont` (the lessons, the answers per repository and the logs; nothing else is stored).

If the `symbiont` command is not found, tell the developer to install it with
`uv tool install 'ai-symbiont[nightly] @ git+https://github.com/smalls257/ai-symbiont'` (the `[nightly]` part brings the packages that train the checker).

---
description: Show what symbiont is doing here, explain a note, silence it, forget a lesson, or answer for this repository
argument-hint: "[status | dashboard | settings | why | mute | forget | lessons | context | reflect | learn-from-prs | allow | decline | mine | nightly | uninstall]"
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
| `nightly [base=<folder> kit=<folder>]` | `symbiont_nightly` with `base` and `kit` only when the developer gave them | `symbiont nightly start` (`--base <folder> --kit-files <folder>`) | train this repository's checker on its lessons, on this machine (nothing is uploaded). It builds the judge kit first if there is none, then trains in the background and returns within a minute with "training started; N lessons; check with `/symbiont status`"; training takes 1-4 minutes and `status` then shows `training job: running`, `done on N lessons at <time>` or `failed: <reason>`. If it fails because there is no kit, relay its steps (download the base and the kit, then run `/symbiont nightly` again with their folders as `base` and `kit`); if it says the nightly packages are missing, give the developer the install command it quotes. Never retry through the shell when the tool answered |
| `dashboard` | `symbiont_dashboard` | `symbiont dashboard`, then `open <address>` on macOS | this repository's dashboard: pain points, lessons, the 30-day replay and the measured results. Tell the developer the address in your reply, so they can open it even if no browser opened |
| `learn-from-prs` | `symbiont_learn_from_prs`, then follow the steps it returns yourself with your own `gh` access | `symbiont learn-from-prs`, then the same | learn lessons from this repository's recent pull-request reviews and CI failures; symbiont reads nothing from GitHub, you save the lessons with `symbiont_add_lessons` (source_label like "from PR #412 review", source_url the PR address) |
| `reflect` | no tool or command; do it yourself now | | answer "In one or two plain sentences each, what non-obvious thing about this repository would you tell a teammate before they work on this area next time? Name the files or areas. Only things that were not obvious from the docs." from the work done in this session, then call `symbiont_add_lessons` with `source_label` "from reflection" (kind `rule` or `mistake`, `files`, `applies_to`); say "nothing" and call no tool if there is nothing |

When the developer points you at notes, reports or lessons they keep, read what they point to, decide in your own words what is worth keeping, and call `symbiont_add_lessons`. When symbiont asks you to review pain points or look for corrections, call `symbiont_review_candidates` or `symbiont_correction_candidates`, judge each item yourself, and save with `symbiont_save_reviews` or `symbiont_save_corrections`. symbiont makes no model calls of its own.

For `uninstall`, run nothing. Tell the developer to remove the plugin with `/plugin uninstall
symbiont@ai-symbiont` in Claude Code, or `muse plugins remove symbiont` in Muse Code, and to remove
the command and its stored data with `uv tool uninstall ai-symbiont` and by deleting the folder
`~/.symbiont` (the lessons, the answers per repository and the logs; nothing else is stored).

If the `symbiont` command is not found, tell the developer to install it with
`uv tool install git+https://github.com/smalls257/ai-symbiont`.

# The symbiont plugin

One bundle, `plugin/symbiont/`, installs symbiont into Claude Code and Muse Code. This page is
the design: what it is made of, the rules it keeps, and the decay each rule prevents.

## What is in the bundle

| Piece | File | Job |
|---|---|---|
| Hooks | `hooks/hooks.json` | session start, prompt submit, tool use and tool failure run `symbiont-hook <event>` |
| Wrapper | `bin/symbiont-hook.sh` | says so, once per session, when the `symbiont` command is missing; always exits 0 |
| MCP server | `.mcp.json` | the one `recall(question)` tool, served by `symbiont mcp` |
| Command | `commands/symbiont.md` | `/symbiont`: status, why a note fired, mute, forget, uninstall help |
| Marketplace | `.claude-plugin/marketplace.json` (repo root) | lets both harnesses install the bundle from GitHub |

The same bundle validates in both harnesses (`claude plugin validate`, `muse plugins validate`).
The two read the same `hooks.json` shape and event names. They differ in one fact the hook needs:
which harness it is running under. Muse Code sets `MUSE_PLUGIN_ROOT` for every plugin hook
and Claude Code does not [measured], so `--harness auto` (the default) reads that variable and one
file serves both.

```mermaid
flowchart LR
  H[harness hook] --> W[symbiont-hook.sh]
  W -->|command missing| V[one visible install line, exit 0]
  W --> C[symbiont-hook]
  C -->|port empty| S[start symbiont serve, detached]
  C --> SV[local service 127.0.0.1]
  S --> SV
  SV --> G{repository gate}
  G -->|not answered| O[onboarding note, nothing stored]
  G -->|declined| Q[silent, nothing stored]
  G -->|allowed| R[exact-repeat rule, then the learner]
  R --> N[note as plain prose]
  MCP[symbiont mcp] --> SV
```

## Rules and the decay each prevents

- **A missing command or a down service is audible.** The wrapper prints the install command; the
  hook starts a down service once (log in `~/.symbiont/service.log`) and otherwise says
  "symbiont offline" and where the log is. Prevents Silent Fallback: an empty note must never read
  as "nothing to warn about".
- **The hook never blocks the agent.** It exits 0 on every path, including unusable input and an
  unusable reply, each printed as one visible line.
  The harness timeout is set to 2 s in the bundle's `hooks.json` [established].
  A warm call took about 60 ms [measured] on one laptop.
  A call that started the service took about 175 ms [measured] on the same laptop.
  The hook has its own entry point so it imports no learner and no numpy.
  A service that cannot start is not restarted for 30 s [established] (`RETRY_AFTER_S`)
  so a crash loop is not a process spawn per tool call.
- **Nothing is stored without a yes, per repository.** The service keeps three states per
  repository: allowed, declined, never asked. Never asked and declined observe nothing and write no
  event. The first session of a never-asked repository shows one note saying what symbiont does,
  that everything stays on this computer, and the three answers (`symbiont repo allow`,
  `symbiont repo mine`, `symbiont repo decline`). Prevents Silent Fallback at the privacy boundary.
  Known limit: a repository is its directory name, as in the record schema, so two checkouts with
  one name share an answer.
- **Day-one value from one lesson.** `core/repeat.py` is the exact-repeat rule: the same command
  failing with the same normalized error as a stored failure that was later fixed gets "Last time,
  `<command>` failed with <error>; it was fixed when you <edit summary>". It reuses the miner's
  failed-command finder, so a planned failure (the TDD red) is never a repeat, and it says each
  lesson once per session. Prevents Paper Tiger: a plugin that needs weeks of history before it may
  speak fails the first-week user.
- **A pass never gets a note.** A note is about a failed command whose normalized failure signature (the failing test and the message, with numbers, paths and hashes normalized) matches a stored lesson. A command and an exception class alone never match, and a passing or unreported result gets nothing.
- **The developer's words lead.** `symbiont context add <lesson id or last> "<words>"` (or `POST /lessons/<id>/context` with `{text, intentional, priority}`) stores words per lesson. The note then reads "[symbiont] In this repo: <words>. Last time …"; `intentional` silences the lesson.
- **A rule reaches the work it applies to.** A lesson with the developer's words is a rule. It is delivered on a prompt, or on a failed command, when a named file is the lesson's file, in its area (a non-generic directory) or has the same stem without `test_`, or when the text shares at least two salient terms with the rule (its own words and the lesson's file stems, stopwords out). One shared word never fires. At most one rule per prompt or failure, high priority first, once per session for a prompt and again only for a new failure message; `intentional` silences it. The event log says which match fired it (`fired_by`) or why it held back. This prevents a Paper Tiger rule that only fires on the exact failure that taught it, and the opposite noise that teaches the agent to ignore notes.
- **Notes are domain prose.** No scores, thresholds or feature names. `recall` takes one question.
- **Every note can be explained and undone.** Events carry the repository and the kind of trouble,
  never text of the prompt. `symbiont why` reads the last note's cause from the log; `symbiont
  mute` silences a kind of trouble; `symbiont forget` deletes its lessons and keeps them silenced
  if they are mined again. Prevents Black Box in the developer's hands.
- **Nightly training is announced once.** When a repository's first night finishes (its nightly
  record appears), the next session start says so, once. Until then the learner is whatever
  `symbiont serve` was started with (plain counters by default).

## Where it lives

| Concern | Module |
|---|---|
| exact-repeat rule (pure) | `src/symbiont/core/repeat.py` |
| answers, silenced notes, announcements | `src/symbiont/store/repos.py` |
| the gate, in front of the learner | `src/symbiont/service/repo_gate.py` |
| the hook command and service start | `src/symbiont/delivery/hook_main.py`, `launch.py` |
| Muse Code and Claude Code session readers | `src/symbiont/readers/muse_code.py`, `claude_code.py` |
| `/symbiont` commands | `src/symbiont/service/operator_commands.py` |

## Not done yet

- No `PreToolUse` hook: no event before a tool runs carries an outcome, so there is nothing to say
  at that moment, and a hook on every tool call costs time. Failures get their note right after
  they happen.
- Muse Code field names (tool calls, JSON shell results with `exit_code`, `find`/`replace` edits) were checked on one throwaway session [measured]; other Muse tools are read as plain results.
- The judge that checks a note against what it learned (nightly training) is switched on by running
  the nightly job; the plugin does not run it.

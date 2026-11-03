# symbiont plugin

Warns your coding agent about mistakes this repository has already made, using your own agent
history. Everything stays on your computer: the plugin only talks to a service on 127.0.0.1.

This folder is the plugin for Claude Code and Muse Code. It needs the `symbiont` command:

```bash
uv tool install git+https://github.com/smalls257/ai-symbiont
```

It adds hooks for session start, prompt submit and tool use, a `recall` tool over MCP, and the
`/symbiont` command (status, why a note fired, mute, forget, uninstall help). The first time you
open a repository it tells you what symbiont does and asks before it stores anything. See
`docs/product/plugin.md` in the repository for the design.

## Install

Claude Code: `/plugin marketplace add https://github.com/smalls257/ai-symbiont`, then `/plugin install symbiont@ai-symbiont`.

Muse Code: `muse plugins marketplace add ai-symbiont https://github.com/smalls257/ai-symbiont`, then
`muse plugins install symbiont@ai-symbiont`.

## Windows

Claude Code on Windows runs the hooks through Git Bash (the default when Git for Windows is
installed), so the `sh` wrapper works unchanged; Windows runs of the test suite in CI prove the
wrapper, the service start and the readers. `uv tool install` puts `symbiont.exe` and
`symbiont-hook.exe` in `%USERPROFILE%\.local\bin`; both wrappers look there. Without Git for Windows
Claude Code falls back to PowerShell, which has no `sh`: run `symbiont install claude-code` in the
project instead (it writes `symbiont hook ...` commands that either shell runs). Session history is
read from `%USERPROFILE%\.claude\projects`.

Muse Code runs on Windows through its official PowerShell launcher, and it runs plugin hooks
through `cmd.exe`, where there is no `sh` [measured on Windows 11, Muse 1.4.14]. Each hook command
therefore tries `symbiont-hook.sh` first and falls back to `bin\symbiont-hook.cmd`, which keeps the
same promise: one "not installed" line at session start, exit 0 always. Muse Code escapes quotes
in the command it hands to `cmd.exe`, so that fallback path is unquoted and a plugin cache path with
a space in it would not run (the hook fails without blocking the agent). Muse Code's history is read
from `%USERPROFILE%\.local\share\muse\sessions` (or `%XDG_DATA_HOME%`); it records the workspace as
`\\?\C:\...`, which the reader treats as the same directory as `C:\...`.

Muse Code's shell tool on Windows also needs its OS sandbox. If a session says "sandbox
enforcement unavailable (setup_required)", run `muse sandbox windows check`, then
`muse sandbox windows setup` once from an elevated (administrator) terminal; it creates the
sandbox users and firewall rules, which symbiont cannot do for you.

To trace in PowerShell: `New-Item $HOME\.symbiont\hook-trace.on -Force`.

## Tracing the hooks

To see what the host sent and what each hook did, run `touch ~/.symbiont/hook-trace.on` (or set
`SYMBIONT_HOOK_TRACE=<file>` where the host passes its environment; Muse Code does not). Each hook
then appends to `~/.symbiont/hook-trace.jsonl`: a `wrapper` line when it starts, a `received` line
with the raw input before any parsing, and an `outcome` line (`forwarded` or `dropped` with the
reason). A `received` with no `outcome` is a hook the host killed. Remove the marker to stop; it
is off by default. The trace holds raw prompts and tool output, so it stays local.

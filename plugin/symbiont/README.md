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

## Tracing the hooks

To see what the host sent and what each hook did, run `touch ~/.symbiont/hook-trace.on` (or set
`SYMBIONT_HOOK_TRACE=<file>` where the host passes its environment; Muse Code does not). Each hook
then appends to `~/.symbiont/hook-trace.jsonl`: a `wrapper` line when it starts, a `received` line
with the raw input before any parsing, and an `outcome` line (`forwarded` or `dropped` with the
reason). A `received` with no `outcome` is a hook the host killed. Remove the marker to stop; it
is off by default. The trace holds raw prompts and tool output, so it stays local.

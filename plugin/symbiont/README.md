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

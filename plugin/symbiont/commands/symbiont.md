---
description: Show what symbiont is doing here, explain a note, silence it, forget a lesson, or answer for this repository
argument-hint: "[status | why | mute | forget | lessons | allow | decline | mine | uninstall]"
allowed-tools: Bash(symbiont:*)
---

You are running the `/symbiont` command. The argument is: $ARGUMENTS

Run exactly one command from this table with the Bash tool, then tell the developer the result in
one or two plain sentences. Never invent output; if a command fails, quote its message.

| Argument | Run | Meaning |
|---|---|---|
| empty or `status` | `symbiont status` | whether symbiont is running, and what it knows about this repository |
| `why` | `symbiont why` | why the last note fired, and what it rested on |
| `mute` | `symbiont mute` | stop notes about the kind of trouble the last note was about |
| `forget` | `symbiont forget` | delete the lessons behind the last note and keep them silenced |
| `lessons` | `symbiont lessons` | list the stored lessons for this repository with their ids |
| `allow` | `symbiont repo allow` | switch symbiont on for this repository |
| `decline` | `symbiont repo decline` | keep symbiont off for this repository |
| `mine` | `symbiont repo mine` | learn from this repository's past agent sessions (needs `allow` first) |

For `uninstall`, run nothing. Tell the developer to remove the plugin with `/plugin uninstall
symbiont@ai-symbiont` in Claude Code, or `muse plugins remove symbiont` in Muse Code, and to remove
the command and its stored data with `uv tool uninstall ai-symbiont` and by deleting the folder
`~/.symbiont` (the lessons, the answers per repository and the logs; nothing else is stored).

If the `symbiont` command is not found, tell the developer to install it with
`uv tool install git+https://github.com/smalls257/ai-symbiont`.

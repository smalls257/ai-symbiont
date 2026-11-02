#!/bin/sh
# Runs `symbiont-hook <event>` for Claude Code and Muse Code, and never lets the host down.
#
# Why a wrapper: a hook whose command is missing fails with "command not found", a line most hosts
# hide. Here a missing install says so once per session, with the command that fixes it, and every
# path exits 0 so the agent is never blocked.
PATH="$HOME/.local/bin:$PATH"
export PATH
# Tracing shows that the host ran this hook even if the command below dies. Muse Code hides the
# user's environment, so the marker file is the switch: see symbiont.delivery.hook_trace.
if [ -f "$HOME/.symbiont/hook-trace.on" ]; then
  printf '{"stage":"wrapper","event":"%s","ts":%s}\n' "$1" "$(date +%s)" >> "$HOME/.symbiont/hook-trace.jsonl"
fi
if ! command -v symbiont-hook >/dev/null 2>&1; then
  if [ "$1" = "SessionStart" ]; then
    printf '%s\n' '{"systemMessage":"symbiont is not installed, so it is off. Install it with: uv tool install git+https://github.com/smalls257/ai-symbiont"}'
  fi
  exit 0
fi
symbiont-hook "$@"
exit 0

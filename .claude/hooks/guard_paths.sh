#!/usr/bin/env bash
# QG-AI-02 PreToolUse hook (Write|Edit|MultiEdit|NotebookEdit). Denies writes the project rules
# forbid, with the rule named on stderr so the agent can route around the action, not around
# the gate:
#   data/, runs/        raw data and run logs are never committed or hand-edited
#   .env*, *.key        secrets
#   the owner's global harness config directory
#   .claude/settings*, .claude/hooks/   the harness gates themselves (owner-edited)
#   gate files: waiver lists, test floor, gitleaks and semgrep config, .importlinter,
#               scripts/gates/, scripts/hooks/  (owner-edited; QG-GATE-01 also checks the diff,
#               because a shell edit bypasses this hook)
#   prereg/*.md whose status is FROZEN   write a dated amendment file instead
#   QG-SEC-06 (edit-time secrets): the text being written is scanned with gitleaks and the repo's
#               own .gitleaks.toml, so a key, private address, home path, e-mail or phone number
#               never reaches the working tree, let alone a commit. Fails closed: no gitleaks or
#               no config denies the write. Weights, datasets and key files are denied by name.
# Exit 2 blocks the tool call. The project root is the edited file's own git toplevel, so a
# worktree under .claude/worktrees/ is judged against itself, not the main checkout.
set -uo pipefail
shopt -s nocasematch   # X.PEM and data.CSV are the same files as x.pem and data.csv

payload=$(cat)
file=$(printf '%s' "$payload" | python3 -c 'import json,sys; t=json.load(sys.stdin).get("tool_input",{}); print(t.get("file_path") or t.get("notebook_path") or "")') \
  || { echo "QG-AI-02: could not read the hook input" >&2; exit 2; }
[ -n "$file" ] || exit 0

deny() { echo "QG-AI-02: refusing to write $file: $1" >&2; exit 2; }

case "$file" in "$HOME"/.claude/*) deny "never edit the owner's global harness configuration" ;; esac

# nearest existing parent directory, so a file in a directory that does not exist yet resolves
dir=$(dirname "$file")
while [ ! -d "$dir" ] && [ "$dir" != "/" ]; do dir=$(dirname "$dir"); done
root=$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null) || exit 0   # not in a repo: not our business
rel="${file#"$root"/}"
[ "$rel" != "$file" ] || exit 0

# Text being written: Write content, Edit new_string, MultiEdit edits, NotebookEdit new_source.
written=$(printf '%s' "$payload" | python3 -c '
import json, sys
t = json.load(sys.stdin).get("tool_input", {})
parts = [t.get(k) or "" for k in ("content", "new_string", "new_source")]
parts += [e.get("new_string") or "" for e in t.get("edits") or []]
sys.stdout.write("\n".join(parts))') || { echo "QG-AI-02: could not read the text being written" >&2; exit 2; }
scan_written_text() {
  [ -n "$written" ] || return 0
  command -v gitleaks >/dev/null 2>&1 || deny "QG-SEC-06: gitleaks is not installed, so the text cannot be checked (brew install gitleaks)"
  [ -s "$root/.gitleaks.toml" ] || deny "QG-SEC-06: $root/.gitleaks.toml is missing, so the text cannot be checked"
  printf '%s' "$written" | gitleaks stdin --config "$root/.gitleaks.toml" --redact --no-banner \
    --log-level error --exit-code 1 >/dev/null 2>&1 \
    || deny "QG-SEC-06: the text holds a credential or private infrastructure detail (key, token, private IP, home path, e-mail, phone, MAC); use an environment variable or a placeholder"
}

case "$rel" in
  tests/fixtures/*|results/*) ;;
  *.parquet|*.safetensors|*.gguf|*.pt|*.pth|*.bin|*.ckpt|*.onnx|*.wad|*.pem|*.p12|*.pfx|*.jsonl|*.traj|*.sqlite|*.sqlite3|id_rsa*|id_ed25519*)
    deny "QG-SEC-06: datasets, weights and key files are never written into the repo (data is never committed)" ;;
esac
case "$rel" in
  data/*|runs/*)   deny "raw data and run logs are never edited by agents (project rule: data is never committed)" ;;
  .env*|*/.env*|*.key) deny "secrets are never written by agents" ;;
  .claude/settings*|.claude/hooks/*) deny "the harness gates are edited by the owner only" ;;
  .lizard-whitelist.txt|.naming-waivers.txt|scripts/gates/*|scripts/hooks/*|scripts/publish/*|.gitleaks*|.semgrep/*|.importlinter|.gitattributes)
    deny "gate files are delete-only and owner-edited (fix the code, never the gate)" ;;
  prereg/*.md)
    if grep -q '^Status: FROZEN' "$file" 2>/dev/null; then
      deny "this prereg is FROZEN; write a dated amendment file instead"
    fi ;;
esac
scan_written_text
exit 0

#!/bin/bash
# Laptop side of the staged calibration: copy the desktop's summary into results/ every INTERVAL
# seconds (runs take minutes, so this tracks every run), commit it once at the end of each stage,
# and exit when the driver finishes, is gated, is blocked, or dies.
# Usage: scripts/calibration/sync_results.sh <repo_root> [interval_s]
# Needs SYMBIONT_DESKTOP_SSH (user@host) and SYMBIONT_DESKTOP_WORKDIR (work dir inside WSL); see env.example.
set -uo pipefail
: "${SYMBIONT_DESKTOP_SSH:?SYMBIONT_DESKTOP_SSH is not set: export user@host of the desktop (see env.example)}"
: "${SYMBIONT_DESKTOP_WORKDIR:?SYMBIONT_DESKTOP_WORKDIR is not set: export the desktop work dir (see env.example)}"
REPO=$1; INTERVAL=${2:-120}
# Overridable so a test can probe for its own fake driver instead of the whole host's process table.
DRIVER_PATTERN=${SYMBIONT_DRIVER_PATTERN:-launch.py|staged.py}
OUT=results/calibration-glimmer.json
remote() { ssh -o ConnectTimeout=15 "$SYMBIONT_DESKTOP_SSH" wsl -d Ubuntu-24.04 --cd "$SYMBIONT_DESKTOP_WORKDIR" -- bash -s; }
commit() {  # $1 = message; retried next cycle if git is busy (another agent committing)
  git -C "$REPO" commit -q -m "$1

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- "$OUT" && echo "committed: $1"
}
cd "$REPO" || exit 1
s1_done=0
while true; do
  if ! echo 'cat runs/calibration-glimmer.json' | remote > "$OUT.tmp" || ! python3 -c "import json,sys;json.load(open(sys.argv[1]))" "$OUT.tmp"; then
    echo "$(date '+%F %T') fetch failed (desktop unreachable or summary mid-write); retrying"; sleep "$INTERVAL"; continue
  fi
  mv "$OUT.tmp" "$OUT"
  status=$(python3 -c "import json;d=json.load(open('$OUT'));print(d['status'], d['n_runs'], d['band_counts'])")
  echo "$(date '+%F %T') $status"
  st=${status%% *}
  if [ "$s1_done" = 0 ] && [ "$st" != running ]; then
    commit "Glimmer calibration stage 1 (screen) results" && s1_done=1
  fi
  case $st in
    done) commit "Glimmer calibration stage 2 (confirm) results" || { sleep 30; commit "Glimmer calibration stage 2 (confirm) results"; }; exit 0 ;;
    gate_fail|blocked) [ "$s1_done" = 1 ] || commit "Glimmer calibration results ($st)"; echo "STOP: $st"; exit 2 ;;
  esac
  if ! echo "pgrep -f '$DRIVER_PATTERN' >/dev/null" | remote; then
    if [ "${dead:-0}" = 1 ]; then  # second look: still not running and not finished -> it crashed
      echo "STOP: driver not running with status $st"; echo 'tail -5 runs/staged.log' | remote; exit 3
    fi
    dead=1; sleep 20; continue  # re-fetch once: it may have just finished
  fi
  sleep "$INTERVAL"
done

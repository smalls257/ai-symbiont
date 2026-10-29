#!/bin/bash
# Detached launcher for one phase of the Django run, from the desktop's swev work dir.
# Endpoints come from a private env file outside the repo; the log gets start and exit lines.
# Usage: launch_swev.sh <workdir> <runs-dir> <swev_launch.py args...>
set -uo pipefail
WORK=${1:?workdir}; RUNS=${2:?runs dir under workdir}; shift 2
ENV_FILE=${SWEV_ENV_FILE:-$WORK/swev.env}
[ -r "$ENV_FILE" ] || { echo "no env file $ENV_FILE (export lines for the arm endpoints)" >&2; exit 2; }
set -a; . "$ENV_FILE"; set +a
mkdir -p "$WORK/$RUNS"
LOG="$WORK/$RUNS/swev.log"
cd "$WORK/repo/scripts/swev" || exit 2
echo "=== start $(date -Is) $*" >> "$LOG"
"$WORK/.venv/bin/python" -u swev_launch.py "$WORK" --runs-dir "$RUNS" "$@" >> "$LOG" 2>&1
echo "=== exit rc=$? $(date -Is)" >> "$LOG"

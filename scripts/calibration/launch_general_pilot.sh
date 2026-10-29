#!/usr/bin/env bash
# General-lessons prompt pilot: plain Glimmer and plain Glimmer + the general card, side by side,
# on the 18 held-out tasks of results/general-split.json. Exploratory, no prereg; not a scored run.
#
#   SYMBIONT_GLIMMER_URL=... GENERAL_PILOT_SERVING_OK=<date> launch_general_pilot.sh WORKDIR
#
# WORKDIR holds calibration-v2/ (CAL2 driver with --lessons), .venv/, data/ and
# runs-general-pilot/{eval-tasks.jsonl,general-card.json}. Both arms run at once with 2 workers
# each, so their runs share the server's 4 slots and the same hours; step cap 50, wall cap 45 min,
# reasoning low (the driver's setting), 1 run per task per arm.
# GENERAL_PILOT_SERVING_OK must name the date verify_glimmer_models.py passed after the serving
# fix: before it, plain requests could carry the sqlglot adapter.
# Exit: 64 usage, 66 missing input, otherwise the worse of the two arms' exit codes.
set -uo pipefail

[[ $# -eq 1 ]] || { echo "usage: launch_general_pilot.sh WORKDIR" >&2; exit 64; }
WORK=$1
PILOT=runs-general-pilot
: "${SYMBIONT_GLIMMER_URL:?SYMBIONT_GLIMMER_URL is not set}"
: "${GENERAL_PILOT_SERVING_OK:?set GENERAL_PILOT_SERVING_OK after verify_glimmer_models.py passes}"
for path in "$WORK/calibration-v2/launch.py" "$WORK/.venv/bin/activate" \
  "$WORK/$PILOT/eval-tasks.jsonl" "$WORK/$PILOT/general-card.json"; do
  [[ -e $path ]] || { echo "launch_general_pilot: missing $path" >&2; exit 66; }
done
TASKS=$(wc -l <"$WORK/$PILOT/eval-tasks.jsonl")
[[ $TASKS -eq 18 ]] || { echo "launch_general_pilot: $TASKS tasks, expected 18" >&2; exit 66; }

cd "$WORK/calibration-v2" || exit 66
# shellcheck disable=SC1091
. ../.venv/bin/activate
LOG="../$PILOT/staged.log"
COMMON=(--candidates-log "$PILOT/eval-tasks.jsonl" --fixed-runs 1 --workers 2
  --step-limit 50 --wall-limit-min 45)

arm() {  # arm <name> [extra driver flags...]
  local name=$1
  shift
  echo "=== start $name serving_ok=$GENERAL_PILOT_SERVING_OK $(date -Is)" >>"$LOG"
  python -u launch.py "$WORK" --runs-dir "$PILOT/$name" "${COMMON[@]}" "$@" >>"$LOG" 2>&1
  local rc=$?
  echo "=== exit $name rc=$rc $(date -Is)" >>"$LOG"
  return $rc
}

arm plain &
PLAIN=$!
arm card --lessons "../$PILOT/general-card.json" &
CARD=$!
wait $PLAIN
PLAIN_RC=$?
wait $CARD
CARD_RC=$?
exit $((PLAIN_RC > CARD_RC ? PLAIN_RC : CARD_RC))

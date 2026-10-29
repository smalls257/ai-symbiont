#!/usr/bin/env bash
# Overnight general-lessons evaluation: waits for the served general adapters, then runs each one
# as an arm (under test) on the 18 held-out tasks, 1 run each, step cap 50, wall cap 45 min.
# The plain and card arms come from the general pilot (reference) and are not rerun; if every
# adapter arm finishes before the deadline, a second plain run is added.
#
#   SYMBIONT_GLIMMER_URL=http://host:port/v1 overnight_general_eval.sh WORKDIR
#
# WORKDIR holds calibration-general/ (CAL2 driver with --served-model), .venv/, data/, and
# runs-general-overnight/{eval-tasks.jsonl,general-split.json}. Polls /health and /v1/models
# every POLL_S; starts nothing while a general-pilot driver runs; never more than 4 requests at
# once (workers split over the arms that start together). Gives up at DEADLINE (05:00 local).
# Everything goes to runs-general-overnight/overnight.log; per-arm counts to summary.txt.
set -uo pipefail

[[ $# -eq 1 ]] || { echo "usage: overnight_general_eval.sh WORKDIR" >&2; exit 64; }
WORK=$1
OUT=runs-general-overnight
DIR="$WORK/$OUT"
LOG="$DIR/overnight.log"
POLL_S=${POLL_S:-120}  # coordinator: poll every 2 minutes
SLOTS=4  # the Glimmer server's slots
ADAPTERS=(Muse-Glimmer-30B-sqlglot-general Muse-Glimmer-30B-sqlglot-habits)
: "${SYMBIONT_GLIMMER_URL:?SYMBIONT_GLIMMER_URL is not set}"
for path in "$WORK/calibration-general/launch.py" "$WORK/.venv/bin/activate" \
  "$DIR/eval-tasks.jsonl" "$DIR/general-split.json"; do
  [[ -e $path ]] || { echo "overnight_general_eval: missing $path" >&2; exit 66; }
done
ROOT=${SYMBIONT_GLIMMER_URL%/v1}
DEADLINE=${DEADLINE:-$(date -d "$( (($(date +%H) >= 5)) && echo tomorrow) 05:00" +%s)}

say() { echo "$(date -Is) $*" >>"$LOG"; }
healthy() { curl -fsS -m 20 "$ROOT/health" 2>/dev/null | grep -q '"ok"'; }
served() { curl -fsS -m 30 "$SYMBIONT_GLIMMER_URL/models" 2>/dev/null | grep -o "\"$1\"" >/dev/null; }
pilot_running() { pgrep -f "launch.py $WORK --runs-dir runs-general-pilot" >/dev/null; }

arm() {  # arm <runs-subdir> <workers> [driver flags...]
  local name=$1 workers=$2
  shift 2
  say "start $name workers=$workers $*"
  (cd "$WORK/calibration-general" && python -u launch.py "$WORK" --runs-dir "$OUT/$name" \
    --candidates-log "$OUT/eval-tasks.jsonl" --fixed-runs 1 --workers "$workers" \
    --step-limit 50 --wall-limit-min 45 "$@" >>"$DIR/staged.log" 2>&1)
  say "exit $name rc=$?"
}

run_together() {  # run_together <adapter names...>: one arm each, sharing the slots
  local workers=$((SLOTS / $#)) name
  for name in "$@"; do arm "${name#Muse-Glimmer-30B-}" "$workers" --served-model "$name" & done
  wait
}

summarize() {
  python3 - "$DIR/general-split.json" "$WORK" >"$DIR/summary.txt" 2>>"$LOG" <<'PY'
import json, pathlib, sys
split, work = json.load(open(sys.argv[1])), pathlib.Path(sys.argv[2])
kinds = {e["task"]: e["kind"] for e in split["evaluation"]}
arms = {
    "plain (reference, pilot)": "runs-general-pilot/plain",
    "card (under test, pilot)": "runs-general-pilot/card",
    "sqlglot-general (under test)": "runs-general-overnight/sqlglot-general",
    "sqlglot-habits (under test)": "runs-general-overnight/sqlglot-habits",
    "plain run 2 (reference)": "runs-general-overnight/plain-run2",
}
print("exploratory: general lessons on the 18 held-out sqlglot tasks, 1 run per task per arm")
for label, sub in arms.items():
    path = work / sub / "calibration.jsonl"
    if not path.is_file():
        print(f"{label}: not run")
        continue
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    graded = [r for r in rows if r.get("resolved") is not None and r["instance_id"] in kinds]
    per = {k: [r for r in graded if kinds[r["instance_id"]] == k] for k in ("bug", "feature")}
    parts = [f"{k} {sum(bool(r['resolved']) for r in v)}/{len(v)}" for k, v in per.items()]
    errors = sum(r.get("error_kind") is not None for r in rows)
    print(f"{label}: solved {sum(bool(r['resolved']) for r in graded)}/{len(graded)} ({', '.join(parts)}); errors {errors}")
PY
  local rc=$?
  ((rc == 0)) || say "summary failed rc=$rc (see the traceback above)"
}

cd "$WORK" || exit 66
# shellcheck disable=SC1091
. .venv/bin/activate
say "armed: deadline $(date -d "@$DEADLINE" -Is), adapters ${ADAPTERS[*]}"
pending=("${ADAPTERS[@]}")
while ((${#pending[@]})) && (($(date +%s) < DEADLINE)); do
  ready=()
  if ! pilot_running && healthy; then
    for name in "${pending[@]}"; do served "$name" && ready+=("$name"); done
  fi
  if ((${#ready[@]})); then
    run_together "${ready[@]}"
    left=()
    for name in "${pending[@]}"; do [[ " ${ready[*]} " == *" $name "* ]] || left+=("$name"); done
    pending=("${left[@]}")
    summarize
    continue
  fi
  sleep "$POLL_S"
done
if ((${#pending[@]})); then
  say "deadline reached; never served: ${pending[*]}"
elif (($(date +%s) < DEADLINE)) && healthy; then
  arm plain-run2 "$SLOTS"
fi
summarize
say "done"

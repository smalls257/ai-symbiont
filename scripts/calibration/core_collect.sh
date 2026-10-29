#!/usr/bin/env bash
# Core collection: plain Glimmer, 2 runs per EARLIER task at step cap 75 (wall cap 45 min), on the
# sqlglot collection list (CAL2 driver, 2 workers) and the Django SWE-Bench-CL history tasks (SWE-bench
# driver, 2 workers) side by side, so at most 4 requests reach Glimmer. Then it writes the manifest
# of passing runs (core_collect_manifest.py) that Route B trains on.
#
#   SYMBIONT_GLIMMER_URL=http://host:port/v1 core_collect.sh WORKDIR
#
# WORKDIR holds calibration-general/, runs-bench/ (Django driver and its env), .venv/, and
# runs-core-collect/{collect-sqlglot.jsonl,core-test-set.json,core_collect_manifest.py}.
# Starts only when ALL hold: runs-core-collect/strix-ok exists (written once the Strix probe is
# done; the desktop cannot read the Strix), /health is ok, and no other Glimmer driver or
# overnight waiter runs. A Bench waiter that is still armed is logged, never killed.
# Log: runs-core-collect/collect.log. Gives up at DEADLINE (epoch seconds, optional).
set -uo pipefail

[[ $# -eq 1 ]] || { echo "usage: core_collect.sh WORKDIR" >&2; exit 64; }
WORK=$1
OUT=runs-core-collect
DIR="$WORK/$OUT"
LOG="$DIR/collect.log"
POLL_S=${POLL_S:-120}
: "${SYMBIONT_GLIMMER_URL:?SYMBIONT_GLIMMER_URL is not set}"
for path in "$WORK/calibration-general/launch.py" "$WORK/runs-bench/repo/scripts/swev/launch_swev.sh" \
  "$DIR/collect-sqlglot.jsonl" "$DIR/core-test-set.json" "$DIR/core_collect_manifest.py"; do
  [[ -e $path ]] || { echo "core_collect: missing $path" >&2; exit 66; }
done
ROOT=${SYMBIONT_GLIMMER_URL%/v1}

say() { echo "$(date -Is) $*" >>"$LOG"; }
healthy() { curl -fsS -m 20 "$ROOT/health" 2>/dev/null | grep -q '"ok"'; }
blocker() {  # prints why collection may not start yet; nothing when it may
  [[ -e $DIR/strix-ok ]] || { echo "no strix-ok marker (Strix probe not done)"; return; }
  pgrep -f 'overnight_general_eval' >/dev/null && { echo "overnight waiter still running"; return; }
  pgrep -f 'python -u (launch|swev_launch)\.py' >/dev/null && { echo "another driver runs"; return; }
  healthy || echo "glimmer /health not ok"
}
past_deadline() { [[ -n ${DEADLINE:-} ]] && (($(date +%s) >= DEADLINE)); }

sqlglot_arm() {
  say "start sqlglot collection"
  (cd "$WORK/calibration-general" && python -u launch.py "$WORK" --runs-dir "$OUT/sqlglot" \
    --candidates-log "$OUT/collect-sqlglot.jsonl" --fixed-runs 2 --workers 2 \
    --step-limit 75 --wall-limit-min 45 >>"$DIR/staged.log" 2>&1)
  say "exit sqlglot collection rc=$?"
}

django_arm() {
  say "start django history collection"
  bash "$WORK/runs-bench/repo/scripts/swev/launch_swev.sh" "$WORK/runs-bench" "../$OUT/django" \
    --phase history --arm plain --runs 2 --step-limit 75 --wall-limit-min 45
  say "exit django history collection rc=$?"
}

mkdir -p "$DIR"
# shellcheck disable=SC1091
. "$WORK/.venv/bin/activate"
say "armed"
pgrep -f bench_waiter >/dev/null && say "note: a Bench waiter is still armed; it may compete"
last=""
while reason=$(blocker); [[ -n $reason ]]; do
  past_deadline && { say "deadline reached before start: $reason"; exit 75; }
  [[ $reason == "$last" ]] || say "waiting: $reason"
  last=$reason
  sleep "$POLL_S"
done
sqlglot_arm &
django_arm &
wait
cd "$WORK" || exit 66
python3 "$DIR/core_collect_manifest.py" --test-set "$DIR/core-test-set.json" \
  --out "$DIR/manifest.jsonl" "$OUT/sqlglot" "$OUT/django" >>"$LOG" 2>&1
say "manifest rc=$? -> $DIR/manifest.jsonl"

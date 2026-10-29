#!/usr/bin/env bash
# The training host's half of `scripts/routeb/nightly.py`: one step per call, each one loud.
#
#   ops/routeb_nightly_host.sh --env FILE train   WORK SET [START_FROM]
#   ops/routeb_nightly_host.sh --env FILE install NAME SET
#   ops/routeb_nightly_host.sh --env FILE verify  WORK NAME
#   ops/routeb_nightly_host.sh --env FILE restore
#   ops/routeb_nightly_host.sh --env FILE ensure-up
#   ops/routeb_nightly_host.sh --env FILE clean   WORK
#
# Exists so Glimmer (the `llama` container) is never left down or serving a broken preset:
# - train runs the adapter job only through ops/gpu_run.sh (it pauses llama and holds both of the
#   other project's GPU locks, and puts llama back as it found it on every exit path);
# - install first proves the running preset is healthy, keeps it as `<preset>.last-good`, writes
#   the personal section (scripts/routeb/glimmer_preset.py), restarts llama and waits until the
#   router lists both names; any failure there restores `.last-good` before exiting;
# - restore puts `.last-good` back and restarts (the caller runs it when verify fails after an
#   install); ensure-up starts llama if a failed step left it stopped. Both wait for health.
# - clean removes the night's training rows and questions (lesson text) from WORK; logs, the
#   adapter and the GGUF stay.
#
# FILE is an untracked env file (hosts and paths never live in the repo). It must set
# ROUTEB_PRESET (the router preset the container reads), ROUTEB_GLIMMER_URL (the router as this
# host reaches it), ROUTEB_PLAIN_MODEL, ROUTEB_SERVE_DIR, ROUTEB_PY, ROUTEB_SNAPSHOT and the
# variables scripts/routeb/train_sqlglot_adapter.sh reads. Optional: ROUTEB_SERVE_DIR_IN_CONTAINER
# (default ROUTEB_SERVE_DIR: the adapter path as the container sees it), ROUTEB_HEALTH_SECONDS
# (600), ROUTEB_HEALTH_POLL (5), and ROUTEB_TRAIN_JOB (default train_sqlglot_adapter.sh; tests
# point it at a stand-in so no GPU job runs).
#
# Exit: 0 done; 1 the step failed and Glimmer is serving the last good preset; 64 usage;
# 66 missing input; 69 Glimmer was unhealthy before install, nothing changed; 70 Glimmer could
# not be brought back: a human must look now.
set -Euo pipefail

readonly CONTAINER=llama
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)

die() { echo "routeb_nightly_host: $2" >&2; exit "$1"; }
say() { echo "routeb_nightly_host: $*" >&2; }

load_env() {
  [[ ${1:-} == --env && -n ${2:-} ]] || die 64 "usage: routeb_nightly_host.sh --env FILE STEP ..."
  [[ -f $2 ]] || die 66 "env file $2 not found"
  set -a
  # shellcheck disable=SC1090
  . "$2"
  set +a
  local name
  for name in ROUTEB_PRESET ROUTEB_GLIMMER_URL ROUTEB_PLAIN_MODEL ROUTEB_SERVE_DIR ROUTEB_PY \
    ROUTEB_SNAPSHOT; do
    [[ -n ${!name:-} ]] || die 64 "$name is not set in $2"
  done
}

lists() {  # lists NAME...: the router answers /models and lists every NAME
  local body name
  body=$(curl -fsS --max-time 10 "$ROUTEB_GLIMMER_URL/models" 2>/dev/null) || return 1
  for name in "$@"; do
    grep -q "\"$name\"" <<<"$body" || return 1
  done
}

wait_healthy() {  # wait_healthy NAME...: poll until the router lists every NAME or time runs out
  local waited=0 limit=${ROUTEB_HEALTH_SECONDS:-600} poll=${ROUTEB_HEALTH_POLL:-5}
  until lists "$@"; do
    if [[ $waited -ge $limit ]]; then
      say "router did not list $* within ${limit}s"
      return 1
    fi
    sleep "$poll"
    waited=$((waited + poll))
  done
}

restart_glimmer() {
  if [[ $(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null) == true ]]; then
    docker restart "$CONTAINER" >/dev/null || return 1
  else
    docker start "$CONTAINER" >/dev/null || return 1
  fi
}

restore() {
  [[ -f $ROUTEB_PRESET.last-good ]] || die 70 "no $ROUTEB_PRESET.last-good to restore"
  cp "$ROUTEB_PRESET.last-good" "$ROUTEB_PRESET" || die 70 "could not write $ROUTEB_PRESET"
  restart_glimmer && wait_healthy "$ROUTEB_PLAIN_MODEL" \
    || die 70 "GLIMMER IS DOWN: restored the last good preset but the router does not answer"
  say "restored the last good preset; Glimmer answers"
}

ensure_up() {
  if lists "$ROUTEB_PLAIN_MODEL"; then return 0; fi
  say "Glimmer does not answer; starting $CONTAINER"
  restart_glimmer && wait_healthy "$ROUTEB_PLAIN_MODEL" \
    || die 70 "GLIMMER IS DOWN: $CONTAINER was started but the router does not answer"
}

train() {
  [[ $# -ge 2 && $# -le 3 ]] || die 64 "usage: train WORK SET [START_FROM]"
  local job=${ROUTEB_TRAIN_JOB:-$ROOT/scripts/routeb/train_sqlglot_adapter.sh}
  [[ -f $1/train/$2/train.jsonl ]] || die 66 "missing $1/train/$2/train.jsonl"
  [[ -z ${3:-} || -d $3 ]] || die 66 "missing previous adapter $3"
  ROUTEB_START_FROM=${3:-} "$HERE/gpu_run.sh" -- "$job" "$1" "$2" \
    || { local rc=$?; say "training failed (exit $rc)"; ensure_up; exit 1; }
  [[ -f $ROUTEB_SERVE_DIR/glimmer-$2.gguf ]] \
    || { say "training finished without $ROUTEB_SERVE_DIR/glimmer-$2.gguf"; ensure_up; exit 1; }
  ensure_up
}

install() {
  [[ $# -eq 2 ]] || die 64 "usage: install NAME SET"
  local name=$1 gguf="glimmer-$2.gguf"
  local in_container=${ROUTEB_SERVE_DIR_IN_CONTAINER:-$ROUTEB_SERVE_DIR}
  [[ -f $ROUTEB_SERVE_DIR/$gguf ]] || die 66 "missing $ROUTEB_SERVE_DIR/$gguf"
  lists "$ROUTEB_PLAIN_MODEL" || die 69 "Glimmer is not healthy before install; nothing changed"
  cp "$ROUTEB_PRESET" "$ROUTEB_PRESET.last-good" || die 69 "could not keep the last good preset"
  python3 "$ROOT/scripts/routeb/glimmer_preset.py" --preset "$ROUTEB_PRESET" \
    --plain "$ROUTEB_PLAIN_MODEL" --personal "$name" --lora "$in_container/$gguf" \
    || { say "preset not written; Glimmer untouched"; exit 1; }
  if ! { restart_glimmer && wait_healthy "$ROUTEB_PLAIN_MODEL" "$name"; }; then
    say "Glimmer did not come back with $name; restoring the last good preset"
    restore
    exit 1
  fi
  say "installed $name ($gguf); the router lists it beside $ROUTEB_PLAIN_MODEL"
}

verify() {
  [[ $# -eq 2 ]] || die 64 "usage: verify WORK NAME"
  [[ -f $1/questions.jsonl && -f $1/system.txt ]] || die 66 "missing questions or system in $1"
  PYTHONPATH="$ROOT/scripts/routeb" HF_HUB_OFFLINE=1 "$ROUTEB_PY" \
    "$ROOT/scripts/routeb/verify_glimmer_models.py" --server "$ROUTEB_GLIMMER_URL" \
    --snapshot "$ROUTEB_SNAPSHOT" --work "$1" --plain "$ROUTEB_PLAIN_MODEL" --adapter "$2" \
    --system "$1/system.txt" || { say "verify failed for $2"; exit 1; }
}

clean() {
  [[ $# -eq 1 ]] || die 64 "usage: clean WORK"
  rm -rf "$1/train" "$1/questions.jsonl" "$1/system.txt"
}

main() {
  load_env "$@"
  shift 2
  local step=${1:-}
  shift || true
  case "$step" in
    train) train "$@" ;;
    install) install "$@" ;;
    verify) verify "$@" ;;
    restore) restore ;;
    ensure-up) ensure_up ;;
    clean) clean "$@" ;;
    *) die 64 "unknown step '$step' (train, install, verify, restore, ensure-up, clean)" ;;
  esac
}

main "$@"

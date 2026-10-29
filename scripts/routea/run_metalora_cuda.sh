#!/usr/bin/env bash
# METALORA on a CUDA GPU: meta-learn starting LoRA adapters (Reptile) and judge them on held-out repos.
#
# Violation prevented: Black Box. Each step logs to its own file under $WORK/logs/ and appends
# "<step> <seconds>" to timing.txt, so a slow or dead step is visible from the outside; set -e stops
# the run at the first failed step. Paper Tiger guard: the Reptile settings are chosen on the
# validation repos only (phase val); the test repos are touched once, in phase test, by the chosen
# start beside the blank start, a joint-trained start with the same updates, floor and ceiling.
#
#   scripts/routea/run_metalora_cuda.sh WORK MODEL val    # every GRID config on the val repos
#   META_PICK=k10-s1.0 scripts/routea/run_metalora_cuda.sh WORK MODEL test
#
# WORK holds data/ (build_meta_domains.py + paraphrase_questions.py output) and a venv with torch,
# transformers and peft at $VENV (default $WORK/venv).
set -euo pipefail

USAGE="usage: run_metalora_cuda.sh WORK MODEL val|test"
WORK=${1:?$USAGE}
MODEL=${2:?$USAGE}
PHASE=${3:?$USAGE}
[[ $PHASE == val || $PHASE == test ]] || { echo "$USAGE" >&2; exit 2; }
HERE=$(cd "$(dirname "$0")" && pwd)
PY="${VENV:-$WORK/venv}/bin/python"
DATA="$WORK/data"
LOGS="$WORK/logs"
STARTS="$WORK/starts"
# Reptile grid, "inner_steps:outer_iters:first_outer_step" each; every config makes the same
# number of inner updates (inner_steps x outer_iters), so they differ in how often they move the start.
GRID=${META_GRID:-"10:300:1.0 30:100:1.0 10:300:0.3"}
# Validation cells "lessons:iters": the short budgets the claim is about.
VAL_CELLS=${META_VAL_CELLS:-"5:15,10:15,10:30"}
mkdir -p "$LOGS" "$STARTS"

timed() {  # timed <step name> <command...>
  local name=$1 start
  shift
  start=$(date +%s)
  "$@" >"$LOGS/$name.log" 2>&1
  echo "$name $(($(date +%s) - start))" >>"$LOGS/timing.txt"
}

config_name() {  # config_name inner:outer:step -> k10-o300-s1.0
  IFS=: read -r inner outer step <<<"$1"
  echo "k$inner-o$outer-s$step"
}

reptile() {  # reptile inner:outer:step
  local name inner outer step
  name=$(config_name "$1")
  IFS=: read -r inner outer step <<<"$1"
  [[ -f "$STARTS/$name/.done" ]] && return 0
  timed "meta-$name" "$PY" "$HERE/meta_train_torch.py" reptile --model "$MODEL" --data "$DATA" \
    --out "$STARTS/$name" --inner-steps "$inner" --outer-iters "$outer" --outer-step "$step"
  touch "$STARTS/$name/.done"
}

joint() {  # joint <iters>
  [[ -f "$STARTS/joint-$1/.done" ]] && return 0
  timed "joint-$1" "$PY" "$HERE/meta_train_torch.py" joint --model "$MODEL" --data "$DATA" \
    --out "$STARTS/joint-$1" --iters "$1"
  touch "$STARTS/joint-$1/.done"
}

if [[ $PHASE == val ]]; then
  starts=(--start blank)
  for config in $GRID; do
    reptile "$config"
    starts+=(--start "$(config_name "$config")=$STARTS/$(config_name "$config")/start.pt")
  done
  first=${GRID%% *}
  IFS=: read -r inner outer _ <<<"$first"
  joint $((inner * outer))
  starts+=(--start "joint=$STARTS/joint-$((inner * outer))/start.pt")
  timed adapt-val "$PY" "$HERE/adapt_answer_torch.py" --model "$MODEL" --data "$DATA" --split val \
    --out "$WORK/answers/val" --cells "$VAL_CELLS" "${starts[@]}"
else
  PICK=${META_PICK:?set META_PICK to the config chosen on the val repos, e.g. k10-o300-s1.0}
  [[ -f "$STARTS/$PICK/.done" ]] || { echo "no finished start $PICK" >&2; exit 2; }
  [[ $PICK =~ ^k([0-9]+)-o([0-9]+)- ]] || { echo "bad META_PICK $PICK" >&2; exit 2; }
  updates=$((BASH_REMATCH[1] * BASH_REMATCH[2]))
  joint "$updates"
  timed adapt-test "$PY" "$HERE/adapt_answer_torch.py" --model "$MODEL" --data "$DATA" \
    --split test --out "$WORK/answers/test" --start floor --start ceiling --start blank \
    --start "meta=$STARTS/$PICK/start.pt" --start "joint=$STARTS/joint-$updates/start.pt"
fi
echo "metalora $PHASE done" >>"$LOGS/timing.txt"

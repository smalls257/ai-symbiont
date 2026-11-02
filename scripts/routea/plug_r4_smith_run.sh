#!/usr/bin/env bash
# Code-fix lessons study, the whole pipeline in one detached script (laptop side):
# frozen-pin check, Spark invent and label (template and public text only), rows, GPU stages on
# the CUDA desktop, the frozen decision. Each step leaves a marker in W/done, so a rerun resumes.
#
#   nohup scripts/routea/plug_r4_smith_run.sh >W/run.log 2>&1 &     (writes W/ALL.DONE)
set -euo pipefail

R=$HOME/symbiont-runs/aidev
W=$R/plug-r4/smith
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
export SYMBIONT_SPEND_CAP_USD=30
: "${SMITH_GPU_HOST:?set SMITH_GPU_HOST (ssh target of the CUDA desktop)}"
: "${SMITH_WIN_USER:?set SMITH_WIN_USER (Windows user name on the desktop)}"
: "${PLUG_CUDA_BASE:?set PLUG_CUDA_BASE (plug-cuda directory inside WSL)}"
HOST=$SMITH_GPU_HOST
WINSCP="C:/Users/$SMITH_WIN_USER"
export SMITH_WIN="/mnt/c/Users/$SMITH_WIN_USER"
SELS=(--selections "$REPO/results/plug-r4-selection.json" "$REPO/results/plug-r4-selection-nightly.json")
mkdir -p "$W/done" "$W/nightly" "$W/out"
cd "$REPO"

step() {  # step NAME CMD...: run once; a marker records that it finished
  local name=$1
  shift
  [[ -f $W/done/$name ]] && return 0
  echo "$(date +%T) $name" >&2
  "$@"
  touch "$W/done/$name"
}
REMOTE="wsl -d Ubuntu-24.04 -- env PLUG_CUDA_BASE=$PLUG_CUDA_BASE SMITH_WIN=$SMITH_WIN bash $SMITH_WIN/plug_r4_smith_remote.sh"
remote() { ssh "$HOST" "$REMOTE $*"; }
launch() {  # launch STAGE: start a GPU stage detached on the desktop and wait for its marker
  remote launch "$1"
  until remote probe "$1"; do
    [[ $? -eq 2 ]] && { echo "GPU stage $1 FAILED" >&2; exit 1; }
    sleep 60
  done
}
launch_local() {  # launch_local STAGE: run a GPU stage here, in the foreground
  bash "$HERE/plug_r4_smith_gpu.sh" "$1"
}
ship() {  # ship TARBALL: copy to the desktop and unpack under smith/
  scp -q "$1" "$HOST:$WINSCP/smith-ship.tgz"
  remote unpack
}

LOCAL=${SMITH_LOCAL:-0}  # 1: run the GPU stages on this laptop's MPS stack (judge venv)
if [[ $LOCAL == 1 ]]; then
  L=$HOME/symbiont-runs/smith-local  # a layout the GPU script expects, linked to local files
  export PLUG_CUDA_BASE=$L LCAP_DEVICE=mps SMITH_DIR=$W SMITH_NO_GPU_GUARD=1
  export SMITH_PY=$HOME/symbiont-runs/judge-venv/bin/python
  mkdir -p "$L/r4c/explore" "$L/models" "$L/r3f" "$L/r4c"
  ln -sfn "$HOME/symbiont-runs/plug-agent/models/llama-3.2-1b-instruct" "$L/models/llama-3.2-1b-instruct"
  ln -sfn "$R/plug-r3-run" "$L/r3f/plug-r3-run"
  ln -sfn "$HOME/symbiont-runs/plug-cuda/data" "$L/data"
  ln -sfn "$REPO" "$L/r4c/repo"
  step models bash -c "
    set -e
    PY=$SMITH_PY; M=$L/models/llama-3.2-1b-instruct; E=$L/r4c/explore
    \$PY scripts/routea/merge_adapter_torch.py --model \$M --adapter $R/plug-r3-run/adapters/judge-s0 --out \$E/base-judge-s0
    scp -q $HOST:$WINSCP/general-adapter.tgz \$E/general-adapter.tgz
    mkdir -p \$E/general-adapter && tar xzf \$E/general-adapter.tgz -C \$E/general-adapter 2>/dev/null
    \$PY scripts/routea/merge_adapter_torch.py --model \$E/base-judge-s0 --adapter \$E/general-adapter --out \$E/base-general
  "
else
  scp -q "$HERE/plug_r4_smith_gpu.sh" "$HERE/plug_r4_smith_remote.sh" "$HERE/plug_r4_combo.sh" "$HOST:$WINSCP/"
  remote install
fi

step check uv run python scripts/routea/plug_r4_smith_decide.py check --items "$W/items" \
  --adapters "$R/plug-r3-run/adapters" "${SELS[@]}" --pins results/plug-r4-smith-pins.json
step invent uv run python scripts/routea/plug_r4_scored_nightly.py invent --out "$W/nightly" --run-cap-usd 3
step label uv run python scripts/routea/plug_r4_cont.py label --pairs "$W/nightly/pairs.jsonl" \
  --out "$W/nightly/labels.jsonl" --run-cap-usd 3
step pairq uv run python scripts/routea/plug_r4_cont.py queries --pairs "$W/nightly/pairs.jsonl" \
  --out "$W/nightly/pair-queries.jsonl"
step pairship bash -c "cp '$W/nightly/pair-queries.jsonl' '$W/pair-queries.jsonl'; tar czf '$W/ship1.tgz' -C '$W' pair-queries.jsonl; true"
if [[ $LOCAL == 1 ]]; then
  step pairs launch_local pairs
  step pairfetch cp "$W/pair-scores.jsonl" "$W/nightly/pair-scores.jsonl"
else
  step pairship2 ship "$W/ship1.tgz"
  step pairs launch pairs
  step pairpack remote pack
  step pairfetch scp -q "$HOST:$WINSCP/smith-pair-scores.jsonl" "$W/nightly/pair-scores.jsonl"
fi
step rows uv run python scripts/routea/plug_r4_scored_nightly.py rows --primary "$W/items" \
  --work "$R/plug-r3-run" --spark "$R/plug-r4/spark" --cont "$W/nightly" \
  --pair-scores "$W/nightly/pair-scores.jsonl" --habits "$R/plug-r4/scored-nightly/habits.jsonl" \
  --out "$W/bundle"
if [[ $LOCAL == 1 ]]; then
  step main launch_local main
else
  step shipmain bash -c "tar czf '$W/ship2.tgz' -C '$W' bundle items"
  step shipmain2 ship "$W/ship2.tgz"
  step main launch main
  step mainpack remote pack
  step fetch bash -c "scp -q $HOST:$WINSCP/smith-out.tgz '$W/smith-out.tgz' && tar xzf '$W/smith-out.tgz' -C '$W'"
fi
step decide uv run python scripts/routea/plug_r4_smith_decide.py decide --items "$W/items" \
  --adapters "$R/plug-r3-run/adapters" "${SELS[@]}" --pins results/plug-r4-smith-pins.json \
  --scores "$W/out" --nightly "$W/combo/scores-habits10" --out results/plug-r4-smith-decision.json
touch "$W/ALL.DONE"

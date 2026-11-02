#!/usr/bin/env bash
# Code-fix lessons study, GPU side (run on the CUDA desktop in WSL, detached):
#
#   plug_r4_smith_gpu.sh pairs   score the Spark-labeled pairs with the round 3 seed-0 judge
#   plug_r4_smith_gpu.sh main    train one nightly adapter per repository, score the items
#
# The GPU is shared with Glimmer, so each stage waits until at least MIN_FREE_MIB of GPU memory
# is free (up to 3 hours) and writes FAILED instead of running if it never is. It never evicts
# anything. SMITH_DIR, SMITH_PY and SMITH_NO_GPU_GUARD=1 let it run on the laptop's MPS stack
# (with LCAP_DEVICE=mps). Writes SM/<stage>.DONE when finished.
set -euo pipefail

STAGE=${1:?usage: plug_r4_smith_gpu.sh pairs|main}
B=${PLUG_CUDA_BASE:?set PLUG_CUDA_BASE to the plug-cuda directory}
R4=$B/r4c/explore SM=${SMITH_DIR:-$B/r4c/explore/smith} PY=${SMITH_PY:-$B/venv/bin/python}
HERE=$B/r4c/repo/scripts/routea
MIN_FREE_MIB=6000
TOTAL_MIB=16303  # RTX 5080

wait_for_gpu() {
  [[ ${SMITH_NO_GPU_GUARD:-0} == 1 ]] && return 0  # unified-memory laptop run: no CUDA memory to read
  for _ in $(seq 1 180); do
    used=$(${NVIDIA_SMI:-nvidia-smi} --query-gpu=memory.used --format=csv,noheader,nounits | head -1 | tr -d '\r ')
    (( TOTAL_MIB - used >= MIN_FREE_MIB )) && return 0
    sleep 60
  done
  echo "gpu never had $MIN_FREE_MIB MiB free" >"$SM/$STAGE.FAILED"
  exit 1
}

wait_for_gpu
case $STAGE in
  pairs)
    "$PY" "$HERE/score_pairs_torch.py" --model "$R4/base-judge-s0" \
      -q "$SM/pair-queries.jsonl" -o "$SM/pair-scores.jsonl" 2>"$SM/pairs.err"
    ;;
  main)
    COMBO=$SM/combo
    mkdir -p "$COMBO/logs" "$SM/out"
    cp -r "$SM/bundle/habits10" "$SM/bundle/queries" "$COMBO/"
    ln -sfn "$R4/base-general" "$COMBO/base-rich-s0"
    cd "$B/r4c/repo"
    SCALES="1" "$HERE/plug_r4_combo.sh" "$PY" "$B/models/llama-3.2-1b-instruct" "$R4" "$COMBO" \
      "$B/data/habit_questions.jsonl" "$B/data/habit_system.txt" >>"$COMBO/logs/combo.stdout" 2>&1
    for seed in 0 1 2; do
      "$PY" "$HERE/score_pairs_torch.py" --model "$B/models/llama-3.2-1b-instruct" \
        --adapter "$B/r3f/plug-r3-run/adapters/judge-s$seed" -q "$SM/items/primary-queries.jsonl" \
        -o "$SM/out/primary-judge-s$seed.jsonl" 2>"$SM/out/score-s$seed.err"
    done
    ;;
  *) echo "unknown stage" >&2; exit 2 ;;
esac
touch "$SM/$STAGE.DONE"

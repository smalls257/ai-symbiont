#!/usr/bin/env bash
# Code-fix lessons study: short helper the laptop runs on the CUDA desktop (inside WSL).
#   plug_r4_smith_remote.sh launch STAGE | probe STAGE | unpack | install | pack
# probe exits 0 when STAGE.DONE exists, 2 when STAGE.FAILED exists, else 1.
set -euo pipefail

SM=${PLUG_CUDA_BASE:?set PLUG_CUDA_BASE}/r4c/explore/smith
WIN=${SMITH_WIN:?set SMITH_WIN to the Windows share as seen from WSL}
case ${1:?usage} in
  launch)
    mkdir -p "$SM"
    rm -f "$SM/$2.DONE" "$SM/$2.FAILED"
    setsid nohup bash "$SM/plug_r4_smith_gpu.sh" "$2" >"$SM/$2.log" 2>&1 < /dev/null &
    disown
    sleep 3
    ;;
  probe)
    [[ -f $SM/$2.DONE ]] && exit 0
    [[ -f $SM/$2.FAILED ]] && exit 2
    exit 1
    ;;
  unpack)
    mkdir -p "$SM"
    tar xzf "$WIN/smith-ship.tgz" -C "$SM" 2>/dev/null
    cp "$WIN/plug_r4_smith_gpu.sh" "$SM/"
    ;;
  install)
    cp "$WIN/plug_r4_combo.sh" "$PLUG_CUDA_BASE/r4c/repo/scripts/routea/"
    chmod +x "$PLUG_CUDA_BASE/r4c/repo/scripts/routea/plug_r4_combo.sh"
    ;;
  pack)
    cd "$SM"
    [[ -f pair-scores.jsonl ]] && cp pair-scores.jsonl "$WIN/smith-pair-scores.jsonl"
    [[ -d out ]] && tar czf "$WIN/smith-out.tgz" out combo/scores-habits10
    ;;
esac

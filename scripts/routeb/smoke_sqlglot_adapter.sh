#!/usr/bin/env bash
# After Glimmer is back with the sqlglot adapter in its preset: one request without and one with
# the adapter (per-request scales), then LCAP-style recall on every held-out sqlglot question in
# both arms. Talks only to the live server; no GPU job of its own.
#
#   scripts/routeb/smoke_sqlglot_adapter.sh SERVER MODEL WORK [SET]
#
# SERVER is the router URL, MODEL the Glimmer model name it lists, WORK the sqlglot work dir.
# Environment: ROUTEB_SNAPSHOT, ROUTEB_PY. Exit 1 when the adapter changes nothing (it is not
# applied, so recall would measure plain Glimmer twice); 66 when MODEL is not listed.
set -Eeuo pipefail

[[ $# -ge 3 ]] || { echo "usage: smoke_sqlglot_adapter.sh SERVER MODEL WORK [SET]" >&2; exit 64; }
SERVER=$1 MODEL=$2 WORK=$3 SET=${4:-sqlglot-all}
HERE=$(cd "$(dirname "$0")" && pwd)
OUT="$WORK/answers/$SET"
py() { PYTHONPATH="$HERE" HF_HUB_OFFLINE=1 OMP_NUM_THREADS=4 nice -n 19 "$ROUTEB_PY" "$@"; }

answer() {  # answer <questions> <out> [--lora 0]
  local questions=$1 out=$2
  shift 2
  py "$HERE/answer_glimmer.py" --server "$SERVER" --model "$MODEL" --snapshot "$ROUTEB_SNAPSHOT" \
    --questions "$questions" --system "$WORK/memory.txt" --out "$out" --adapters 1 "$@"
}

curl -fsS "$SERVER/models" | grep -q "\"$MODEL\"" || { echo "smoke: $MODEL not listed" >&2; exit 66; }
mkdir -p "$OUT/smoke"
py -c 'from sqlglot_rows import MEMORY_SYSTEM; print(MEMORY_SYSTEM, end="")' >"$WORK/memory.txt"

head -1 "$WORK/questions.jsonl" >"$OUT/smoke/q1.jsonl"
answer "$OUT/smoke/q1.jsonl" "$OUT/smoke/without.jsonl"
answer "$OUT/smoke/q1.jsonl" "$OUT/smoke/with.jsonl" --lora 0
echo "without adapter: $(cat "$OUT/smoke/without.jsonl")"
echo "with adapter:    $(cat "$OUT/smoke/with.jsonl")"
if cmp -s "$OUT/smoke/without.jsonl" "$OUT/smoke/with.jsonl"; then
  echo "smoke: the adapter changed nothing; check the preset's lora line and the server log" >&2
  exit 1
fi

answer "$WORK/questions.jsonl" "$OUT/floor.jsonl"
answer "$WORK/questions.jsonl" "$OUT/adapter.jsonl" --lora 0
py "$HERE/score_sqlglot_recall.py" --work "$WORK" --answers "$OUT" --out "$WORK/recall-$SET.json"

# routeb: memory in weights, from the same lessons

See root CLAUDE.md for the repo rules. This file covers `src/symbiont/routeb/`.

**Purpose.** Memory is the LoRA: derive training pairs from lessons (`dataset`), then train, serve and evaluate a personal Glimmer LoRA (Route B) on the local GPU host. Route A uses the same lessons for a small LoRA (Llama 3.2 1B or 3B, license check first) that writes a one-line note. The first test is capacity: 10, 30 and 100 lessons in one adapter, scored on reworded questions and the invented-detail rate; if capacity is low, one adapter per group and a picker.

**Violation prevented: Silent Fallback (a made-up target).** Every completion is the pain point's own stored quote, never a paraphrase, and when history holds no correction for a pain point the derivation is empty with a stated reason. `dataset.py` (which pain points become examples), `signal_texts.py` (how each is worded and quoted) and `lesson_rows.py` (the nightly job's rows from stored lessons: self-study Q&A answered by the three-part lesson card, situation to corrected action only when the lesson holds a fix, one held-out verify question per lesson) are pure (records in, examples out); train, serve and evaluate are periphery.

## Invariants
- Not mistakes, so never examples: breakage of a hub module, rework of a file the session made for itself (same rule the learners use).
- Hold-out ids are enforced: `HoldOutViolationError` before any scored task's trajectory becomes an example.
- Correction targets come from `miner.resolutions`, shared with lessons: a failed command's target is what changed before it passed, then the passing run.
- No raw history is stored: records reach `dataset` re-read from the harness logs; stored lessons reach training only through `store.training` (`lessons_for_personal_model` here, `lessons_for_memory_model` for anything Spark can reach).
- GPU jobs run only through `ops/gpu_run.sh`, one at a time. No sudo, no touching the docker stack.
- Size limits are the pure-core ones (30 lines, CCN 10) even for periphery files here.

## Imports
- May import: core, miner, records, and `eval.budget` only. Must not import the grader (import-linter contract) or delivery/service.

## Commands
`uv run pytest tests/routeb -q`

## Review focus
Is each completion the pain point's stored quote? Could a scored-task trajectory reach the training set?

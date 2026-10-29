# Plug situation pilot: untrained readers on agent situations (2026-10-29)

Exploratory; no prereg. Laptop MLX, Llama 3.2 1B Instruct, on the 10 validation repos (the a3 rerun's). Results: `results/plug-situation-pilot.json`. Code: `scripts/routea/plug_situation.py` (items, ranker, scorer) and `scripts/routea/answer_contexts.py` (one model load, a system prompt per row); tests in `tests/scripts/test_plug_situation.py`.

## Design

- **Situations.** Each of the 83 items is built from one lesson's short fields: the failed command, the file and the error. Every fourth lesson of a repo is a silence item, which leaves 63 pick items and 20 silence items [measured].
- **Prompts.** Each prompt holds 60 lessons: the applicable one, the repo's other lessons, then other repos' lessons. A silence prompt leaves out the lesson its situation came from. A first build drew all distractors from other repos, so the repo name gave the answer away (ranker recall@5 1.00). It was replaced before anything was scored [measured].
- **Readers.** Plain 1B (a1) and a2v (meta-trained on questions with lessons in the prompt). Each answers the 60-lesson prompt, and also the top 5 lessons from a lexical ranker.

## Results

| Prompt | Reader | Pick | Silence | Wrong pick | Says "no lesson" on pick items |
|---|---|---|---|---|---|
| 60 lessons | plain 1B | 0.00 | 0.05 | 0.09 | 0.10 |
| 60 lessons | a2v | 0.00 | 1.00 | 0.00 | 1.00 |
| top 5 | plain 1B | 0.00 | 0.90 | 0.00 | 0.94 |
| top 5 | a2v | 0.00 | 1.00 | 0.00 | 1.00 |

All rows are [measured]; rates are means over repos. Ranker recall [measured]: the applicable lesson ranks first in 0.75 of pick items, in the top 3 in 0.94, and in the top 5 in 0.98.

## Reading

- **Neither untrained reader ever states the applicable fix**, with 60 lessons or with 5 [measured].
- With 5 lessons, both say no lesson applies on almost every pick item [measured]. The prompt offers that answer, and a 1B model takes it.
- a2v was trained on questions, not situations. Its perfect silence is the same "no lesson" answer given to everything, not discrimination [measured].
- **The ranker is not the bottleneck** (0.98 in the top 5) [measured]. The reader is. Round 2 therefore trains a reader on situation rows, with the ranker in front (`prereg/2026-10-29-plug-situations-DRAFT.md`).
- Every pick is 0, so the pilot gives no spread for a minimum detectable effect. The draft computes it from the selected variant's validation spread, before scoring.

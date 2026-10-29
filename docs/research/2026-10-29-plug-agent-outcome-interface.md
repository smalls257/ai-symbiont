# Plug agent outcome, phase 1: interface spec for the build

For the Core agent, who runs mini-SWE-agent on Spark. The design and its fixed words are in `prereg/2026-10-29-plug-agent-outcome-DRAFT.md`. This page says what to build and which existing code to call. Nothing here changes round 3 (`prereg/2026-10-29-plug-judge.md`), and the build never touches its 40 scored repos.

## Inputs

| What | Where |
|---|---|
| Lesson pool | `~/symbiont-runs/t47/data/nebius-openhands/pool`, read with `build_lessons._candidates` then `plug.distinct` (as `plug_r3_run.bundle` does) |
| Task repos | round 3's validation repos: `plan.json["validation"]` in `~/symbiont-runs/aidev/plug-r2-run/` |
| Tasks | the pool's `instance_id`s in those repos, 51 in all [measured]; keep those whose SWE-rebench image pulls and whose gold patch passes and empty patch fails |
| Judge | Llama 3.2 1B plus `adapters/judge-s0`, `judge-s1`, `judge-s2` from `plug_r3.sh train` |
| Thresholds | `selection.json["thresholds"]["judge"]` and `["ranker_threshold"]` from `plug_r3_run.py fit` |

## The store for one task

1. Exclude the 40 scored repos' lessons entirely.
2. Exclude the lessons mined from this task's own instance, and from every instance created after it (SWE-rebench `created_at`; an undated instance is excluded). Log the count each rule removed. `lesson_id` is the first 12 hex digits of sha1 of `session_id:step` (`lessons._build`), so map each pool trajectory's session to its `instance_id` and drop that instance's lessons.
3. The candidate list matches round 3's items, so the thresholds keep their meaning: all of the repo's remaining lessons, plus a sample of other repos' lessons (seeded by the instance id) up to `plug_situation.PROMPT_LESSONS` in total. The ranker's inverse-document-frequency weights are computed over this list, so a store of a different size would shift the ranker threshold.

## A situation from the live run

After each executed command whose return code is not 0 (and only then):

- `failed` = `lessons.shown_command(command)`
- `program, file` = `symbiont.miner.commands.normalise_command(failed)` (as `lessons._build` uses it)
- `error` = `lessons.error_line(output)`; if it returns None, no situation and no note (the lessons were mined the same way)
- situation = `plug_situation.situation_of`'s wording with those fields and the task's repo: ``Ran `{failed}` in {repo} (file {file}). It failed: {error}``

At most one note per distinct `(failed, error)` per run; a repeat of the same failure gets nothing new.

## Choosing the note (per arm)

Build an `Item(item_id, situation, candidates, None)` and call:

- **`rag`:** `plug_situation.lexical_rank(item)[:3]`, always.
- **`ranker`:** `plug_r3.ranker_choices([item], ranker_threshold)`. A lesson id, or None.
- **`judge`:** `plug_judge.shortlist(item, 10)`, then each pair is `plug_judge.pair_prompt(situation, lesson)` under `plug_judge.JUDGE_SYSTEM`. Score P(yes) with each adapter as `score_pairs_torch.py` does (the yes and no tokens are 9891 and 2201) and average over the three adapters. Take the highest; note it if it reaches the judge threshold, else nothing. This is `plug_judge.choose` on one item.
- **`none`:** the wrapper in `WrapMode.PLAIN`.

Serve the judge as a loopback HTTP process next to the harness (CUDA on the 5080 or CPU on the laptop), with one model and three adapters loaded once. It answers one call per failed command, about 10 pairs [established]. A judge that is down must stop the run with an error, never send the arm on with no notes.

## Injecting the note

Use `symbiont.delivery.mini_swe_wrapper`'s pattern: wrap the environment, and on a failed command append the note to that command's observation, under the `[symbiont]` tag line (`tagged`), so it reaches the model in its next turn. The note is the lesson's stored text, `Lesson.text()`, verbatim; `rag` appends three such lines. A local note source (the four arms above) replaces the service call; everything else (`execute`, `serialize` with the arm name) stays as it is.

## Run settings and order

All arms read one config, `plug-agent-1.json`, with the fields and order the prereg's "Agent settings" and "Order and the cost cap" sections fix, pinned by sha256; refuse any other hash. Each task's arms all run before the next task starts, and the cost cap is checked only between tasks.

## What to log per run

Arm, instance id, solved, the failed commands' `(program, error class)` keys, which lesson ids were shown and when, the judge's top P(yes) per call, and tokens in and out from the egress size log. Never log prompt text.

## Repeated known mistakes

For each failed command, the key is `(error class from lessons.ERROR_CLASS, program)`. The command counts as a repeated known mistake if any lesson in that task's store has the same `(error_class, program)`. Count it the same way in every arm.

## Out of scope

Retraining the judge, other thresholds, and the 40 scored repos. Phase 2 (`PLUG-AGENT-2`) is sized from this phase's spread.

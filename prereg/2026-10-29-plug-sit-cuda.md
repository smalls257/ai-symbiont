# Pre-registration: Plug round 2, a trained reader on agent situations (PLUG-SIT)

**FROZEN 2026-10-29.** Code pinned at `db31c8c` (this commit's parent; `plug_r2_score.py check` enforces it). Committed alone at the freeze, before any answer on the scored repos exists. Validation answers of the variants may exist before the freeze; scored answers may not. After the freeze only a dated amendment may change anything, and an amendment cannot change the data, split, variants, selection rule, scorers, metric or decision rule below.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or by construction, [hypothesis] = a guess the run can support or refute.

Owner-proxy rulings applied: `.superpowers/rulings/2026-10-29-plug-situations.md` (15 items plus freeze-check edit 16).

Supersedes `prereg/2026-10-29-plug-situations.md`, frozen in commit 233f2ff on an unmerged branch and withdrawn before any variant ran. It trained each variant with one seed, and the CUDA port found a large seed-to-seed spread for the same 1B start (new-lesson recall 0.47 to 0.93 across seeds on 2 repos) [measured, `.superpowers/sdd/2026-10-27-ai-symbiont-build-plan/plug-cuda-report.md`]. That frozen file's own terms forbade changing the selection rule by amendment, so a second freeze, `prereg/2026-10-29-plug-sit-seeds.md` (commit e456cee, never pushed, nothing run), added three seeds per variant. This file replaces that one too: it adds the CUDA training backend so the twelve trainings run on the 5080 desktop instead of taking a day on the laptop.

Round 1 (`prereg/2026-10-29-l2l-a2.md`, H1 tie) stays reported as it is; this round does not re-slice it.

Code: the variants and the scored run use the code in the freeze commit's tree, driven by `scripts/routea/plug_r2.sh` (`validate`, then `score`).

**Where it runs.** Variant training and answering run on the 5080 desktop (CUDA) with `TRAINER_BACKEND=cuda`: `train_lora_torch.py` (PyTorch + PEFT, the MLX recipe copied step for step) and `answer_contexts_torch.py` (the same greedy decoding). The CUDA-port agent runs them from a clean checkout of the freeze commit and hands back the answers; selection and scoring run on the laptop. The CUDA trainer gave recall identical to MLX from the same laptop weights (0.733 on both), and seed spread is the same effect on both machines [measured, `.superpowers/sdd/2026-10-27-ai-symbiont-build-plan/plug-cuda-report.md`]. If the desktop is unavailable, the declared fallback is `TRAINER_BACKEND=mlx` on the laptop with the same rows, seeds and rule. `selection.json` and the results file record the backend. Its first step, `plug_r2_score.py check`, refuses to train or score unless the code under `scripts/routea`, `scripts/aidev` and `src` at HEAD equals the freeze commit's tree (`plug.pinned_code_commit`), the inputs match their pins, and the plan matches the table below. The results file (`results/plug-situations.json`) carries `code_commit`, `freeze_commit`, `prereg_sha256` and the answer script's sha256. Answers come from `scripts/routea/answer_contexts.py`: greedy decoding, `MAX_TOKENS = 96`, chat-template date "26 Jul 2024", the whole answer folded onto one line. Answers from any other setting are not pooled with these.

## Amendments

(none at freeze)

## Question

An agent is in a situation: a command it is running, a file and an error. The memory holds many lessons, mostly irrelevant. A lexical ranker passes its top 5 lessons, shuffled, to a reader. The reader either writes one note that states the applicable lesson's fix, or stays silent when no lesson applies. Does a reader trained for this (the selected variant) pick the applicable lesson more often than the plain model given the same prompt, on 40 repos neither has been tested on? Does it stay silent when nothing applies? The claim covers this recipe and this pool only. No speed-of-learning words.

## What the pilot already saw (exploratory, validation repos only)

All on the 10 validation repos (`results/plug-situation-pilot-v2.json`, the reviewed design; the first pilot, `results/plug-situation-pilot.json`, stays reported):
- **Untrained readers fail.** With 60 lessons or with the shuffled top 5, plain 1B and a2v (a reader trained on questions, not situations) pick 0.00 [measured]. On the top 5 they say no lesson applies on 0.94 and 1.00 of pick items [measured].
- **The ranker** (`plug_situation.lexical_rank`, word overlap weighted by inverse document frequency) puts the applicable lesson first in 0.735 of pick items and in the top 5 in 0.976 [measured].
- **The ranker-alone row** (its top-1 note as the answer) picks 0.735 and states a wrong fix on 0.62 of items. This is the bar for a trained reader [measured].
- **The scorer can be passed.** No pick item scores its own correct note as a miss (0 at both prompt sizes) [measured].

## Data and split

- **Lessons.** LCAP lessons (one failed command, its error, the command that fixed it) from the public nebius OpenHands pool (CC-BY-4.0), deduplicated per repo (`plug.distinct`), excluding T46's scored repos (`warm_start.BLOCKED`). The input pins of `prereg/2026-10-29-l2l-a2.md` apply (`plug.PINNED`).
- **Fresh repos.** 51 repos with 3 to 7 distinct lessons were not test repos in any earlier Plug run [measured]. They were meta-training repos of round 1's a2 and of a2v. Therefore every variant is trained from plain weights, with a meta-train list that excludes the scored and validation repos, and never from a2v's adapter.
- **Scored repos.** The 40 fresh repos with the lowest sha256 of the UTF-8 `owner/name` string (hex compared as text) are scored. `plug_round2.py plan` wrote this table before any answer [measured]. They hold 165 lessons; 14 repos have 3 lessons, 15 have 4, 4 have 5, 6 have 6 and 1 has 7 [measured]. The scored runner refuses a plan that differs.

| Scored repo | Distinct lessons | Name sha256, first 12 |
|---|---|---|
| sunpy/sunpy | 4 | 0beeef1adaa4 |
| dwavesystems/dwave-system | 6 | 12f7d112037e |
| devopshq/artifactory | 4 | 130a43ab16a4 |
| yt-dlp/yt-dlp | 4 | 13245a3ba858 |
| nosarthur/gita | 4 | 1e54e60eb636 |
| codalab/codalab-worksheets | 6 | 226eb9c5a980 |
| lincc-frameworks/nested-pandas | 4 | 287d04637722 |
| pypa/virtualenv | 4 | 2b78a79968e0 |
| DOV-Vlaanderen/pydov | 3 | 2e51e18bab75 |
| awdeorio/mailmerge | 6 | 31f2ce6b57d1 |
| PyCQA/flake8-bugbear | 3 | 36f340a88de2 |
| mwouts/jupytext | 5 | 38be20a6dbc5 |
| AzureAD/microsoft-authentication-library-for-python | 4 | 3a7981e1084b |
| optuna/optuna | 3 | 4876613a7246 |
| ncclient/ncclient | 6 | 4a00df09e86f |
| andialbrecht/sqlparse | 3 | 4bff2045fef5 |
| pypa/setuptools_scm | 5 | 52e743ecd018 |
| BAMWelDX/weldx | 3 | 55d5e9ed093a |
| psf/black | 4 | 5871f27f38ef |
| graphql-python/graphene-django | 3 | 5e874e8c7e85 |
| fjosw/pyerrors | 4 | 6556ad26b484 |
| missionpinball/mpf | 5 | 65dc10e7cd55 |
| dwavesystems/dwave-cloud-client | 4 | 6b499d5a020e |
| omni-us/jsonargparse | 4 | 7dd651eda76c |
| nltk/nltk | 3 | 7eaa32b1a3bd |
| zalando-stups/senza | 6 | 81a088556cd3 |
| hgrecco/pint-pandas | 5 | 820af82e3632 |
| matchms/matchms | 3 | 85abb0152ae6 |
| pre-commit/pre-commit-hooks | 3 | 86d710000362 |
| TheFriendlyCoder/friendlypins | 3 | 8bda66ae4e8f |
| Materials-Consortia/optimade-python-tools | 3 | 91ce17e1bc60 |
| bids-standard/pybids | 4 | 9448dfe69834 |
| keras-team/keras-nlp | 4 | 94d309fe4bfa |
| mikedh/trimesh | 3 | 9df1e677d98b |
| tophat/syrupy | 3 | a70dcb6591cd |
| python-cmd2/cmd2 | 3 | a734d74e1911 |
| mhostetter/galois | 4 | a746365650f7 |
| datalad/datalad | 7 | a78ff4b92d7f |
| narwhals-dev/narwhals | 4 | b0369b2721cb |
| sqlfluff/sqlfluff | 6 | b241f1ae50d2 |

- **Meta-joining fresh repos** (the other 11): RockefellerArchiveCenter/DACSspace (6), algorand/pyteal (3), hgrecco/pint (5), macbre/sql-metadata (3), microsoft/electionguard-python (3), miurahr/aqtinstall (4), nteract/papermill (4), reata/sqllineage (4), reframe-hpc/reframe (3), scverse/scanpy (3), spdx/tools-python (3) [measured].
- **Validation repos.** The 10 repos of the a3 rerun (`results/plug-a3-rerun.json`, 83 lessons) [measured]. All variant selection happens here.
- **Meta-training repos.** Every other pool repo with lessons: the 11 above, the 34 unused small repos, and the round-1 scored and feasibility repos, 309 lessons in all [measured]. `plug.check_unseen` raises before every variant trains on any repo or lesson id shared with the validation or scored repos.

## Items

`plug_situation.build_items` gives each lesson one pick item and one silence item. The pick prompt holds 60 lessons: the lesson, the repo's other lessons, then lessons of other repos. Distractors never share the lesson's `(error class, fix tokens)` key; 23 such lessons were kept out on the validation repos [measured]. The silence prompt is the pick prompt without that lesson, with the same distractor sample. The ranker's top 5 of each prompt go to the reader in an order shuffled per item (seed 0, `plug_situation.narrowed`). In validation the applicable lesson came first in 13 of 83 shuffled prompts, against 0.735 in ranker order [measured]. Every repo therefore has as many silence items as pick items.

## Scorer

`plug_situation.verdict`, per item:
- **Matching.** Answer text is folded (quotes stripped, whitespace collapsed), split on whitespace, and stripped of edge punctuation. A lesson's fix counts as stated when every token in `added` occurs as a whole token, or the fix command occurs as a contiguous run of whole tokens.
- **Pick (primary).** The note states the applicable lesson's fix and no other shown lesson's fix.
- **Wrong pick.** The note states the fix of a shown lesson that does not apply. Lessons the applicable lesson's note (`Lesson.text()`) itself names are excused: 46 in the validation pick prompts, printed per repo [measured]. `plug_situation_cli.build` refuses any item whose own correct note would not score as a pick.
- **Useful note.** Pick, and the note names the error class.
- **Silence.** On a silence item the answer abstains (`plug.abstains`) and states no shown lesson's fix.
- **Pick-item abstention.** Printed for every row. A reader that abstains everywhere passes silence and fails H1; that is the intended trap.

## Variants and the selection rule (fixed before any variant runs)

Each variant changes one thing from the current best and is trained from plain weights with three seeds (0, 1, 2; `LORA_SEED`). It runs on the validation repos only. Every rule below reads a variant's per-repo rates averaged over its three seeds (`plug_r2_select.seed_mean`) [established]. They run in this order:

1. **V1, situation reader (1B).** LoRA (rank 16, scale 2, all layers, learning rate 1e-4 cosine, batch 4, 1 epoch) with a training window of 1,024 tokens (`LORA_MAX_LENGTH=1024`), on three kinds of rows (`plug_r2_rows.py`) [established]:
   - a2v-style question rows (`l2l_quick.meta_rows` on the V1 meta-train list, capped at 1,600, rows over 1,300 characters dropped);
   - the 202 AIDev habit rows;
   - one pick row and one silence row per meta-train lesson, with prompts built exactly as the test's: a 60-lesson prompt and the ranker's shuffled top 5.

   Targets are the applicable lesson's note (`Lesson.text()`), or "No lesson I hold covers that." on a silence row. `fit_rows.py` drops and counts every row whose target exceeds 96 tokens (the answer budget) or whose whole row exceeds 1,024 tokens under the Llama 3.2 chat template [established].
   - **Why 1,024.** The situation rows' median is 521 tokens, and 349 of 618 exceed 512, so a 512 window would drop most of them; none exceeds 1,024 [measured].
   - **V1's rows (dry run, before any training).** 60 meta-train repos; 1,321 question rows, 202 habit rows and 618 situation rows; 24 rows dropped for targets over 96 tokens (from the 5 long-note meta lessons) and none for length, leaving 2,117 [measured].
   - **Scored long notes.** The 3 scored lessons whose note exceeds 96 tokens stay, since a pick needs only the fix tokens [measured].
2. **V2, many rewordings.** 15 situation phrasings per lesson instead of 1: the test's phrasing plus the 14 fixed templates in `plug_r2_rows.PHRASINGS`. Validation and scoring use only `plug_situation.situation_of`.
3. **V3, more variety.** 2 AIDev habit lessons (the template-built lessons file written by `scripts/aidev/build.py`, train split; sha256 `197d0d0b05ca51cbfc1ec6e0f2f6126874f835e78e101cf91434e9b6771debd5`, pinned in `plug_r2_score.PINNED`, so `check` refuses any other file) added to each training situation prompt as unrelated lessons (`plug_r2_rows.with_unrelated`). Training rows only; test prompts are unchanged.
4. **V4, 3B.** The current best variant's rows on Llama 3.2 3B, three seeds. V4 runs only if 1B "tops out", meaning neither V2 nor V3 replaced the current best. If V4 is selected, every plain-model row in the scored run is Llama 3.2 3B with the same prompt.

**Selection rule.**
- **V1 against the floor.** V1 replaces plain 1B as the current best only if (a) its pick minus plain 1B's pick, paired by repo, has a mean of at least +0.05 with the 95% interval's lower bound above 0, and V1 passes the absolute abstention gate (below) on the validation repos [established]. Plain 1B's validation silence is "no lesson" said to everything, so it never sets a silence bar. If V1 fails, the round stops: V2 to V4 do not run, and the scored run compares plain 1B with the untrained ranker-alone row and reports the floor.
- **From V2 on,** a variant replaces the current best only if (a) holds against the current best, (b) its silence is not lower than the current best's by more than 0.05, and (c) its wrong pick is not higher by more than 0.02. A tie keeps the earlier variant.
- **Selection amendment.** `plug_r2_select.py` applies this rule and computes the MDE (`selection.json`). The selected variant, its validation numbers and the MDE go into a dated amendment committed before any scored answer.
- **Other workstreams.** Spark-written targets, full fine-tuning and the CUDA port enter only through a dated amendment before their first validation answer.

## Rows and labels (scored repos)

| Row | Prompt | Label |
|---|---|---|
| plain model | the same shuffled top 5 | floor (plain model, same prompt; the primary comparison) |
| plain model | situation only, no lessons | floor (pick above 0 means the situation text gives the fix away) |
| selected reader | the same shuffled top 5 | under test |
| selected reader | situation only, no lessons | floor (pick above 0 means it memorized a scored lesson) |
| ranker alone | none: its top-1 lesson's note is the answer | reference (the reader must add something to the ranker's first guess) |

## Hypotheses

- **H1 (primary).** Selected reader minus plain model, pick, paired over the 40 scored repos. The selected reader is its variant trained with the same three seeds; its per-repo rates are the seed mean. The plain model decodes greedily, so it has one answer per item. Expected: `better` [hypothesis].
- **H2 (gate).** The selected reader passes the abstention gate below.
- Everything else is secondary and never decides.

## Decision rule

- **H1.** `better` if the 95% interval's lower bound is above 0 and the mean gain is at least 0.05; `worse` if the upper bound is below 0; otherwise `tie` [established]. Intervals are percentile bootstrap intervals over repos (10,000 resamples, seed 0) [established].
- **H2, abstention gate (pass/fail), over all 40 repos.** Silence at least 0.80 with the interval's lower bound above 0.60, and wrong pick at most 0.05 [hypothesis]. The owner may tighten these numbers before the freeze, never loosen them after. A reader that is `better` on H1 and fails H2 is reported as "picks more and fails the abstention gate", never as a win.
- **Secondary, with fixed words.** Selected reader minus ranker alone, pick. If it is not `better`, the report says "the reader adds nothing the ranker's first guess did not".
- **Claim sentence (built in code).** If H1 is `better` and H2 passes: "picks the applicable lesson in X of situations on 40 unseen repos, against Y for the plain model with the same prompt, and stays silent in Z of situations with no applicable lesson". Otherwise: "the trained reader did not measurably beat the plain model", with the interval.

## Minimum detectable effect (stated before scoring)

Let s be the per-repo standard deviation of the selected variant's validation pick gain over the floor, with the variant's rates averaged over its three seeds. Validation repos hold 8.3 pick items on average and scored repos 4.1 [measured], so s is scaled for the scored repos as s_scored = s·√(8.3/4.1) [established]. This is still a lower bound, since repos differ more than items. The minimum detectable effect is MDE = max(0.05, 1.96·s_scored/√40) + 0.84·s_scored/√40 [established]. It goes into the selection amendment. If the selected variant's validation gain is below its own MDE, the prereg says the expected read is `tie`, and the scored run still happens.

## Downstream check (sized; a separate prereg, never decides this round)

- **Design.** The mini-SWE-agent wrapper (`symbiont.delivery`) is run with a coding model (Glimmer, or Spark if approved) on SWE-rebench task images of the 40 scored repos. There are two arms: notes from the selected reader, and notes from the plain model, both given before each step.
- **Measures.** Resolved rate, and the repeated-mistake rate: a failed command that matches the `failed` of a note the agent was shown.
- **Disjointness.** A downstream task is never the task whose trajectory produced a lesson in the notes.
- **Size.** Detecting a +10 point resolved rate needs about 150 tasks per arm, from binomial power at a base rate near 0.35 [hypothesis]. This workstream runs on the laptop with no spend, so the check is sized here and run elsewhere.

## Known limits

- **Order leak.** It is closed by the per-item shuffle, but the ranker-alone row remains the number the reader must exceed: 0.735 of pick items are its top 1 [measured].
- **Ranker tuning.** The lexical ranker is tuned to situations that quote the lesson's own fields; a paraphrased situation is untested.
- **Coarse per-repo pick.** 40 small repos give per-repo pick in steps of 1/3 to 1/7 [measured].
- **Forking paths and seeds.** Three seeds per variant reduce, but do not remove, seed noise; the seed mean is the unit of every rule. Up to four variants run on 10 validation repos, bounded by the fixed order and the frozen selection rule.
- **Containment scoring.** The scorer matches whole tokens and excuses lessons the right note names. An answer that quotes several fixes is a wrong pick.
- **Multiplicity.** About five intervals at 95% with no correction (H1, ranker alone, useful note, silence, wrong pick) [established].

## Spend and machine

No paid spend. Training and answering run on the 5080 desktop (CUDA); a 1B update of 5 lessons with replay took 30 s at 7.1 GB there, against about 265 s on the laptop [measured, CUDA port report]. Up to four variants with three seeds each, so up to twelve trainings. The laptop timings, the fallback, are: V1 and V3 about 20 minutes per seed, V2 (15 phrasings) about 70 minutes per seed [hypothesis from row counts and the pilot timings]. Validation answers take about 6 minutes per seed [hypothesis]. If V4 runs, 3B training takes about 2.5 times as long [hypothesis]. The scored run answers 330 items for the plain rows and three times for the reader rows, about 40 minutes [hypothesis]. On one laptop the validation stage may take most of a day [hypothesis].

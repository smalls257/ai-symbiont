# Pre-registration: Plug round 2, a trained reader on agent situations (PLUG-SIT)

**DRAFT, NOT FROZEN.** Committed alone at the freeze, before any variant answers a validation item and before any answer on the scored repos exists. After the freeze only a dated amendment may change anything, and an amendment cannot change the data, split, variants, selection rule, scorers, metric or decision rule below.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or by construction, [hypothesis] = a guess the run can support or refute.

Round 1 (`prereg/2026-10-29-l2l-a2.md`, H1 tie) stays reported as it is; this round does not re-slice it.

## Amendments

(none at freeze)

## Question

An agent is in a situation: a command it is running, a file and an error. The memory holds many lessons, mostly irrelevant. A lexical ranker passes the top 5 lessons to a 1B reader, which either writes one note that states the applicable lesson's fix, or stays silent when no lesson applies. Does a reader trained for this (the selected variant below) pick the applicable lesson more often than plain Llama 3.2 1B given the same prompt, on 40 repos neither has seen? Does it stay silent when nothing applies? The claim covers this recipe and this pool only. No speed-of-learning words.

## What the pilot already saw (exploratory, validation repos only)

All on the 10 validation repos (`results/plug-situation-pilot.json`, `docs/research/2026-10-29-plug-situation-pilot.md`):
- **Untrained readers fail.** With 60 lessons in the prompt, plain 1B and a2v (a reader trained on questions, not situations) picked the applicable lesson on 0 of 63 items [measured]. With the ranker's top 5 they still picked 0 of 63. They said no lesson applies on 59 and 63 of the 63 items where one does [measured]. A situation-trained reader is therefore required.
- **The ranker** (`plug_situation.lexical_rank`: inverse-document-frequency overlap of words between the situation and each lesson's repo, program, file, failed command and error class) put the applicable lesson in the top 5 for 62 of 63 items, and first for 47 [measured]. Each prompt's distractors include the repo's other lessons, so the repo name does not give the answer away.

## Data and split

- **Lessons.** LCAP lessons (one failed command, its error, the command that fixed it) from the public nebius OpenHands pool (CC-BY-4.0), deduplicated per repo (`plug.distinct`), excluding T46's scored repos (`warm_start.BLOCKED`). The input pins of `prereg/2026-10-29-l2l-a2.md` apply (`plug.PINNED`; pool index sha256 a14f22f0...).
- **Scored repos.** 51 repos with 3 to 7 distinct lessons appear in no earlier Plug test (206 lessons) [measured]. The 40 with the lowest sha256 of their name are scored; the plan stage writes their names and counts before any answer exists. The other 11 join meta-training.
- **Validation repos.** The 10 repos of the a3 rerun (`results/plug-a3-rerun.json`, 8 or 9 lessons each). All variant selection happens here; the scored repos are never answered before the freeze of the selection result (below).
- **Meta-training repos.** Every remaining pool repo with lessons: the 11 fresh repos above, the 34 unused small repos (44 lessons), and the round-1 scored and feasibility repos (224 lessons), whose test roles are finished [measured]. `plug.check_unseen` raises on any repo or lesson id shared with the validation or scored repos.
- **Items.** `plug_situation.build_items` makes one item per lesson. Every fourth lesson of a repo becomes a silence item: its prompt holds the repo's other lessons but not that one. A prompt holds 60 lessons (the applicable one, the repo's other lessons, then other repos' lessons), and the ranker's top 5 go to the reader. The 20 scored repos with 3 lessons have no silence item; silence is averaged over the repos that have one.

## Variants and the selection rule (fixed before any variant runs)

Each variant changes one thing from the current best. They run in this order, on the validation repos only, each trained once (seed 0):

1. **V1, situation reader (1B).** a2v's recipe (`l2l_quick.meta_rows`, LoRA rank 16, 1 epoch), with situation rows added. A row's prompt is a top-5 lesson list for a meta-train situation; the target is the applicable lesson's note (`Lesson.text()`), or "No lesson I hold covers that." when none applies. V1 becomes the current best if it beats plain 1B by the rule below; otherwise the round stops and reports the untrained floor.
2. **V2, many rewordings.** 15 situation phrasings per lesson instead of 1 (fixed templates written before the run), unseen in validation and scoring.
3. **V3, more variety.** AIDev habit lessons (template-built, `scripts/aidev`) added to prompts as unrelated lessons.
4. **V4, 3B.** The current best recipe on Llama 3.2 3B. It is tried only if 1B "tops out": the last two 1B variants each changed validation pick by less than +0.03. If not, V4 is skipped and recorded as skipped.

Spark-written targets, full fine-tuning and the CUDA port are other workstreams. They enter this round only through a dated amendment before their first validation answer.

**Selection rule.** A variant replaces the current best only if, on the validation repos, all three hold:
- (a) pick minus the current best's pick, paired by repo, has a mean of at least +0.05 with the 95% interval's lower bound above 0 [established];
- (b) its silence rate is not lower than the current best's by more than 0.05;
- (c) its wrong-pick rate is not higher by more than 0.02.

Otherwise the current best stays; a tie keeps the earlier, cheaper variant. The selected variant, its validation numbers and the minimum detectable effect (below) are written into a dated amendment and committed before any scored answer.

## Rows and labels (scored repos)

| Row | Reader | Label |
|---|---|---|
| plain 1B, same top-5 prompt | Llama 3.2 1B | reference (floor of the claim) |
| selected reader, top-5 prompt | the selected variant | under test |
| selected reader, no lessons | the selected variant | floor (pick above 0 means it memorized a scored lesson) |
| ranker alone | none | reference: the top-1 lesson's note pasted as the answer |

## Metrics

Scored per item by `plug_situation.verdict`, averaged per repo, then over repos with a percentile bootstrap (10,000 resamples of repos, seed 0) [established]:
1. **Pick (primary).** The note carries the applicable lesson's fix, meaning every fix token or the fix command, and no other lesson's fix.
2. **Useful note.** Pick, and the note names the lesson's error class.
3. **Silence.** On silence items the answer abstains (`plug.abstains`) and states no lesson's fix.
4. **Wrong pick.** The answer states the fix of a lesson that does not apply.

## Minimum detectable effect (stated before scoring)

With the per-repo standard deviation s of the selected variant's validation pick gain over plain 1B, the 95% half-width at 40 repos is 1.96·s/√40. Under the rule's 0.05 floor, the gain with 80% power to read `better` is 0.05 + 0.84·s/√40. Both numbers go into the selection amendment [established]. For orientation, round 1's question test had s = 0.13, which gives 0.041 and 0.068 [measured, a different test].

## Decision rule

- **Primary:** selected reader minus plain 1B, pick, paired by repo over the 40 scored repos. `better` if the interval's lower bound is above 0 and the mean is at least 0.05; `worse` if the upper bound is below 0; otherwise `tie`.
- **Abstention gate (pass/fail).** The reader passes only if its silence rate is at least 0.80 and its wrong-pick rate is at most 0.05, both means over repos, with the silence interval's lower bound above 0.60 [hypothesis; the owner may tighten these before the freeze, never loosen them after]. A reader that is `better` on pick but fails the gate is reported as "picks more and fails the abstention gate", never as a win.
- **Claim sentence (built in code):** if both hold, "picks the applicable lesson in X of situations on 40 unseen repos, against Y for the plain model with the same prompt, and stays silent in Z of situations with no applicable lesson". Otherwise: "the trained reader did not measurably beat the plain model", with the interval.
- **Secondary, never deciding:** useful note, the ranker-alone row, and the no-lessons floor.

## Downstream check (sized, not part of this decision)

Does a coding agent given the reader's notes solve more tasks and repeat fewer mistakes than one given the plain model's notes? This needs a coding model (Glimmer or Spark) and SWE-rebench task images on the desktop. Neither is available to this workstream: it runs on the laptop with no spend. It is sized here and pre-registered separately: 2 arms, each run on unscored tasks of the 40 scored repos [hypothesis on the pool's task counts].

## Known limits

- Situations are built from the lesson's own fields, so the failed command in a situation matches the lesson's text. That is the warning case the product targets, and it makes ranking easier than a paraphrased situation would.
- One seed per variant. Selection on 10 validation repos, with up to four variants, is a forking path; it is limited by the fixed order, the one-change rule and the frozen selection rule.
- Repos with 3 lessons have no silence item.
- The scorer is token containment. An answer that quotes every lesson is caught by the wrong-pick rate.

## Spend and machine

Laptop MLX, no paid spend [established by the workstream brief]. Per variant: meta-training about 15 minutes, validation answers about 5 minutes [hypothesis from the a2v and pilot timings]. Scored run: about 20 minutes [hypothesis].

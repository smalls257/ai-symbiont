# Pre-registration DRAFT: a meta-learned starting LoRA adapter on held-out repos (METALORA)

**DRAFT, NOT FROZEN.** This file is the proposal for the scored run. It becomes a prereg only when
the owner renames it without `-DRAFT`, adds the freeze marker and commits it alone, before any
scored-split number exists. Until then no scored run may cite it.

Claim tags: [measured] = observed in our own run, [established] = known from the literature or
the code's own documented behavior, [hypothesis] = a guess the run can support or refute.

## Question

Does a LoRA start meta-learned with Reptile across public repos let Llama 3.2 1B learn a new
repo's lessons with fewer training steps than a blank LoRA start, and does it beat a start trained
jointly on the same meta-training lessons (no meta-learning)? A lesson is one failed command, its
error and the command that fixed it, mined from the public nebius OpenHands trajectories by the
LCAP lesson builder. The claim is about steps and lessons on this recipe, stated as "reaches X
recall with N lessons in M steps"; no speed-of-learning claim beyond that.

## Why a second split

The exploratory run (`results/meta-lora-exploratory.json`, report in
`.superpowers/sdd/2026-10-27-ai-symbiont-build-plan/metalora-report.md`) already looked at its five
test repos and chose the Reptile settings on its five validation repos. Those ten repos cannot be
the scored test set. The scored run takes its held-out repos from the repos the exploratory run
never held out.

## Data and split

- Lessons: `scripts/routea/build_meta_domains.py` on the public pool (125 repo files, one
  unreadable and skipped by name; 513 distinct lessons over 76 repos used) [measured]. Lesson
  order inside a repo is by lesson id (a hash), so the 3- and 5-lesson sets nest.
- Scored test repos: every repo holding 5 to 9 distinct lessons (23 repos [measured from the
  per-repo counts]). None of them was a validation or test repo in the exploratory run.
- Meta-training repos: every other repo with 3 or more lessons, including the ten exploratory
  held-out repos. `meta_domains.check_held_out` raises on any shared repo or lesson.
- Sizes: 3 and 5 lessons per test repo (a 5-to-9-lesson repo cannot be taught 10).

## Arms and row labels

- floor: base model, no adapter, no lessons.
- ceiling: the taught lessons in the system prompt.
- blank start (reference): LCAP's adapter (rank 16, all linear layers, scale 2) from peft's seeded
  init, trained by the LCAP recipe (warmup plus cosine lr, peak 1e-4, batch 4, plain Adam without
  bias correction, length-sorted batches).
- joint start (reference): the same init trained on every meta-training row at constant lr 1e-4
  for as many updates as the Reptile run makes.
- meta start (under test): Reptile, first order, over the LoRA weights only, with the settings the
  exploratory run picked on its validation repos and no new tuning: 30 inner updates per repo at
  constant lr 1e-4, 100 outer iterations, outer step 1.0 annealed linearly to 0, repos visited in
  shuffled full passes (seed 0), init seed 0 (`k30-o100-s1.0` in the results file).
- Every start is then taught a test repo's lessons by the same LCAP recipe for 0, 8, 15, 30 updates
  and LCAP's full budget (8 epochs: 36 and 60 updates), one seed per cell.

## Metrics

- Primary: template recall (the LCAP deterministic scorer: the error class or every token the fix
  added, verbatim) at 5 lessons and 15 updates, averaged per repo, meta minus blank and meta minus
  joint, paired by repo.
- Secondary: the same at 3 lessons and 15 updates; meta minus blank at LCAP's full budget (the
  exploratory run saw the meta start fall behind there, so this checks for harm); paraphrased-question recall; invented-detail
  rate (details no lesson of that repo names); the fewest updates at which each start matches the
  blank start's full-budget recall.

## Decision rule

- "Meta start learns from fewer steps than a blank start" holds if the paired percentile bootstrap
  interval at 95% coverage [established] (10,000 resamples over the
  test repos, seed 20261028) of meta minus blank at the primary cell lies above 0, and meta's
  invented-detail rate at that cell is no more than blank's plus 0.05.
- "It is learning to learn, not format pretraining" additionally needs the interval of meta minus
  joint at the primary cell above 0. If meta beats blank but not joint, the result is reported as
  "a pretrained start helps; Reptile adds nothing measurable over joint training".
- Ties and intervals touching 0 are reported as no difference. No other cell can rescue a failed
  primary.

## Process

- Exploratory numbers are not evidence for the scored claim. The scored run is one pass; a crash or
  a bug fix is a dated amendment committed before the re-run.
- Spend: none (the owner's RTX 5080 and laptop). Estimated time on the 5080 [hypothesis]: about
  an hour for the meta and joint starts, an hour for 23 repos x 3 starts x 2 sizes x 5 budgets.

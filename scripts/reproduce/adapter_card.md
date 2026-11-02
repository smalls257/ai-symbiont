---
license: other
license_name: llama3.2
license_link: https://github.com/meta-llama/llama-models/blob/main/models/llama3_2/LICENSE
base_model: meta-llama/Llama-3.2-1B-Instruct
library_name: peft
tags:
  - lora
  - peft
  - llama
  - ai-symbiont
---

# Llama-3.2-1B-symbiont-judge-adapters

**Built with Llama.** Llama 3.2 is licensed under the Llama 3.2 Community License, Copyright (c)
Meta Platforms, Inc. All Rights Reserved. A copy of the license is in `LICENSE` and the required
notice is in `NOTICE`. Use must also follow Meta's Acceptable Use Policy
(https://www.llama.com/llama3_2/use-policy).

These are **LoRA adapters only**. They contain no Llama weights. The base model,
`meta-llama/Llama-3.2-1B-Instruct`, must be obtained from Meta or from Hugging Face under Meta's
license; this repository does not provide it, nor any merged copy of it, nor any training data.

They belong to the ai-symbiont reproduction kit
(`REPRODUCE.md`, tier 3). Claim tags: [measured] is observed in our own run, [established] is
true by construction, [hypothesis] is a guess a run can support or refute.

## What is in here

Every adapter is LoRA rank 16, scale 32, on all seven projection matrices of Llama 3.2 1B
Instruct, for one yes-or-no question: "does this stored lesson apply to this failure?". The
judge's score is the probability of "yes".

| Folder | What it is |
|---|---|
| `judge-s0`, `judge-s1`, `judge-s2` | The round 3 judge, three training seeds. Their mean P(yes) is the judge's score. |
| `general` | The general judge of round 4, trained on top of `base-judge-s0` (below). |

**Withheld:** the two nightly per-repository adapters of the code-fix study (pydantic and moto) are
not published, pending a check of the terms that apply to the model-written training targets. So
the 0.611 code-fix result can be verified from committed counts (tier 2 of the kit) but cannot yet
be rescored from published weights. What can be rescored: the round 3 judge on the 924 items of the
code-fix study (it answers nothing there, as committed).

`adapter_config.json` names the base model by its public Hugging Face id. Training happened on
other machines; no local path is kept.

## How to use them (rebuild the stack)

The adapters stack. Merge each stage into the previous one, then apply the next adapter:

1. `base-judge-s0` = Llama-3.2-1B-Instruct with `judge-s0` merged in.
2. `base-general` = `base-judge-s0` with `general` merged in.
3. The three round 3 judge adapters are each applied on top of the plain Llama-3.2-1B-Instruct.
   (The nightly adapters, withheld, were applied on top of `base-general`.)

The ai-symbiont repository does the judge part of this: `scripts/reproduce/rerun_learning.py fetch-adapters` and `rescore`
download this repository at a pinned revision, check every file against SHA-256 pins, rebuilds
the judges, score the 924 items of the code-fix study and compare with the committed result
inside stated bands. Merged copies are never uploaded; you build them locally.

## Training data and a disclosure

The withheld nightly adapters were trained on lessons mined from public SWE-smith trajectories
(`SWE-bench/SWE-smith-trajectories`, MIT license on its dataset card) for pydantic and moto, with
situations and labels written by a language model from template-built lesson text. The training
data itself is not published here. **The bugs in SWE-smith are synthetic and injected**; the
agents' mistakes while fixing them are real. Failures are inferred from error text because the
observations carry no exit code, and tasks are ordered by a seeded hash because they have no dates.

## Measured result (not rescorable from the published weights)

On 924 items (462 later recurrences and 462 negatives) of two repositories [measured]:
the nightly arm covers 0.611 of recurrences against 0.000 for the agree rule, a gain of +0.611
with a task-clustered interval [0.556, 0.666] [measured]; 5 of 924 picks were wrong, exact
Clopper-Pearson 95% upper bound 1.26% [measured]. The off-the-shelf round 3 judge never said yes on
this data, so the comparison shows that nightly training recovers coverage where the judge does not
transfer (a domain gap), not that training beats a working baseline [established]. Two
repositories, synthetic bugs and a new lesson definition limit the claim to this kind of data.

## Limits

Two repositories from one benchmark. Adapters were trained and merged on a laptop (MPS) and on a
CUDA machine, so numerics may differ in the last bits when you rebuild. Not for use as a general
code model: each adapter answers one yes-or-no question.

# Plug demo, Saturday morning, laptop only

Goal: Glimmer works in a public repository that already has many stored lessons, hits a failure it
met before, receives the stored note (only if the ranker and the 1B judge agree), and does not repeat it.
Total about 25 minutes the first time, about 8 once the store and models are warm. Nothing here
runs from CI; every step names what to check before moving on.

## Before you start (once, about 10 minutes, offline)

1. Merge into this branch (they live on other branches): `scripts/routea/plug_judge_server.py`
   (plug/agent-1) and its imports `score_pairs_torch.py`, `train_lora_torch.py`; the three round-3
   judge adapters `judge-s0..s2` (round-3 bundle). `uv sync --group dev`.
2. Pick the repository: the round-4 primary manifest `results/plug-r4-primary-manifest.json`
   (plug/round3) lists scored repositories with a real recurrence. Choose one with at least 20
   lessons from earlier tasks; call it `ORG__REPO`. Its earlier public sessions are exported by code
   (the SWE-rebench pool script of plug/round3), never read by hand.

## Commands

```bash
export PROJECT=ORG__REPO DATA=$HOME/symbiont-runs/plug-demo SESS=<exported earlier-task jsonl dir>
# 1. store of earlier lessons (public sessions only; the later recurrence task stays out)   ~1 min
for f in $SESS/*.jsonl; do SRC="$SRC --source openhands=$f"; done
uv run symbiont mine --project $PROJECT --data-dir $DATA $SRC       # expect: lessons stored, coverage
# 2. judge: Llama 3.2 1B + 3 seed adapters on the laptop GPU (MPS), loopback only            ~1 min load
LCAP_DEVICE=mps uv run python scripts/routea/plug_judge_server.py --model $LLAMA_1B \
  --adapter $R3/judge-s0 --adapter $R3/judge-s1 --adapter $R3/judge-s2 --port 8791 &
# expect on stderr: judge ready on 127.0.0.1:8791 adapters=3  (each scored pair about 1-3 s on MPS)
# 3. service with the agree rule (first night; add --nightly-dir $DATA/nightly after a night)
uv run symbiont serve --data-dir $DATA --judge-url http://127.0.0.1:8791 &   # port 7391
# 4. delivery into the harness (MCP recall tool + hooks), in the demo checkout
uv run symbiont install claude_code --project-dir $DEMO_CHECKOUT
# 5. Glimmer as the agent on the laptop (existing Glimmer preset; URL from your environment)
SYMBIONT_GLIMMER_URL=<glimmer>/v1 <mini-SWE-agent command of plug/agent-1 plug_agent runner> \
  --task <recurrence task id of $PROJECT>                                   # about 5-10 min
```

## What you should see

- The agent runs the command that failed before and gets the same error.
- It asks `recall` with the situation line ("Ran `cmd` in ORG/REPO (file F). It failed: ERROR").
- Service log: `agreed` verdict, note shown verbatim ("What happened: ... Check: ..."); on a
  non-matching failure, "nothing in this project's history matches that question".
- The agent applies the stored fix on the next step instead of repeating the failure.
- Judge down: 503 and "symbiont offline", never an empty note. Stop the judge to show that.

## Known gaps (do not promise on stage)

- The judge only sees lessons with a command fix; the note-on-failure hook (`/observe`) still uses
  the old path. The demo goes through the recall tool, with the agent asking when it fails.
- With few lessons the ranker score stays under 10.0 and the rule stays quiet: that is why the
  repository needs 20 or more lessons.
- Nightly: after a night, `TRAINER && uv run python scripts/routea/nightly_record.py ...` and a second
  judge server (one adapter) per repository; the service then uses it at 0.98.

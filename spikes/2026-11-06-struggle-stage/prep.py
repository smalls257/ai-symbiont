"""Throwaway: aggregate sqlglot traces into the mockup's data.json (approximates plan Task 2)."""
import collections, json, sys, os
from pathlib import Path
from symbiont.readers import READERS
from symbiont.records.schema import Kind
from symbiont.miner.mine import sessions_of, mine_history
from symbiont.miner.lessons import lessons_from
from symbiont.miner.painpoint import Signal
from symbiont.miner.commands import normalise_command

SRC, META, OUT = sys.argv[1:4]
PROBE = {"ls","cat","head","tail","find","stat","file","which","type","pwd","wc","du","tree","grep","rg","cd"}
meta = json.load(open(META))
recs = list(READERS["openhands"](Path(SRC), "sqlglot"))
sessions = sessions_of(recs)
by = {(r.session_id, r.step): r for r in recs}
month_of_task = {t: v["created_at"][:7] for t, v in meta.items()}
sess_task = {s[0].session_id: s[0].task_id for s in sessions}
sess_month = {sid: month_of_task.get(t, "unknown") for sid, t in sess_task.items()}

def in_repo(f):
    f = f.lstrip("./")
    return f.startswith(("sqlglot/", "tests/", "docs/")) and f.endswith(".py")

def outcome(lesson):
    prog = lesson.pain_point.signature.key[0]
    if prog in ("C-c", "C-d", "C-z"): return "interrupt"
    if prog in PROBE: return "probe"
    if lesson.resolution:
        steps = [by[r] for r in lesson.sources[1:] if r in by]
        if any(s.kind == Kind.EDIT for s in steps) or len(lesson.resolution) > 1: return "fixed"
        return "respelled"
    why = lesson.unresolved_because or ""
    return "never" if why.startswith("no later") else "unclear"

lessons = [l for l in lessons_from(mine_history(sessions, {}), recs) if l.pain_point.signature.signal == Signal.FAILED_COMMAND]
out_counts = collections.Counter(outcome(l) for l in lessons)

# churn: edits per in-repo file per session; rework turns = edits beyond the first
churn = collections.Counter()
for s in sessions:
    for r in s:
        if r.kind == Kind.EDIT:
            for f in r.files:
                if in_repo(f): churn[(f.lstrip("./"), r.session_id)] += 1
scratch_edits = sum(1 for s in sessions for r in s if r.kind == Kind.EDIT and r.files and not any(in_repo(f) for f in r.files))

# struggle per (file, session): unfixed failures whose target is the file + rework turns
struggle = collections.Counter()
for (f, sid), n in churn.items():
    if n >= 3: struggle[(f, sid)] += n - 1
for l in lessons:
    oc = outcome(l)
    if oc in ("respelled", "never", "unclear"):
        tgt = l.pain_point.signature.key[1] if len(l.pain_point.signature.key) > 2 else "-"
        if in_repo(tgt): struggle[(tgt.lstrip("./"), l.pain_point.session_id)] += 1

months = sorted({m for m in sess_month.values() if m != "unknown"})
sess_per_month = collections.Counter(sess_month[s] for s in sess_month)
file_total = collections.Counter()
for (f, sid), v in struggle.items(): file_total[f] += v
top_files = [f for f, _ in file_total.most_common(14)]
heat = []
for f in top_files:
    row = []
    for m in months:
        sids = {sid for (ff, sid), v in struggle.items() if ff == f and sess_month[sid] == m}
        row.append({"sessions": len(sids), "share": round(len(sids) / sess_per_month[m], 3) if sess_per_month[m] else 0})
    heat.append({"file": f, "total_turns": file_total[f], "sessions": len({sid for (ff, sid) in struggle if ff == f}), "cells": row})

# traps: fixed groups seen in >= 2 sessions
groups = collections.defaultdict(list)
for l in lessons:
    if outcome(l) == "fixed": groups[l.pain_point.signature.key].append(l)
traps = []
for key, ls in groups.items():
    sids = {l.pain_point.session_id for l in ls}
    if len(sids) < 2: continue
    per_month = collections.Counter(sess_month[l.pain_point.session_id] for l in ls)
    traps.append({"program": key[0], "target": key[1] if len(key) > 2 else "", "broke": key[-1],
                  "sessions": len(sids), "occurrences": len(ls),
                  "fix": ls[-1].resolution[0][:110] if ls[-1].resolution else "",
                  "by_month": [per_month.get(m, 0) for m in months]})
traps.sort(key=lambda t: -t["sessions"])

# one session strip: the session with the most struggle
worst = collections.Counter()
for (f, sid), v in struggle.items(): worst[sid] += v
sid = worst.most_common(1)[0][0]
sess = next(s for s in sessions if s[0].session_id == sid)
strip = []
for r in sess:
    if r.kind == Kind.COMMAND:
        prog = normalise_command(r.command or "")[0]
        strip.append({"step": r.step, "type": "fail" if r.exit_code not in (None, 0) else "pass", "label": f"{prog} {normalise_command(r.command or '')[1]}"[:60]})
    elif r.kind == Kind.EDIT:
        f = (r.files or ("?",))[0].lstrip("./")
        strip.append({"step": r.step, "type": "edit" if in_repo(f) else "scratch", "label": f[:60]})
    elif r.kind == Kind.USER_TURN:
        strip.append({"step": r.step, "type": "user", "label": "user message"})

json.dump({
    "dataset": "nebius OpenHands traces, tobymao/sqlglot",
    "sessions": len(sessions), "tasks": len(set(sess_task.values())),
    "failures": len(lessons), "outcomes": out_counts,
    "edits_in_repo": sum(churn.values()), "scratch_edits": scratch_edits,
    "months": months, "sessions_per_month": [sess_per_month[m] for m in months],
    "heat": heat, "traps": traps[:12], "trap_count": len(traps),
    "strip": {"session": sid[:10], "task": sess_task[sid], "steps": strip},
}, open(OUT, "w"), indent=1)
print("ok", out_counts, len(traps), len(months), sid[:8], len(strip))

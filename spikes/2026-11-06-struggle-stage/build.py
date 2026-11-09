"""Throwaway: per-session facts for the click-through mockup (sqlglot traces). Counts and labels only."""
import collections, json, re, sys, time
from pathlib import Path
from symbiont.readers import READERS
from symbiont.records.schema import Kind
from symbiont.miner.mine import sessions_of, mine_session
from symbiont.miner.lessons import lessons_from
from symbiont.miner.painpoint import Signal
from symbiont.miner.commands import normalise_command
from symbiont.service.dashboard_view import MINUTES_PER_TURN

import types
_src = open(Path(__file__).parent / "themes.py").read()
TH = types.SimpleNamespace()
_ns = {"__name__": "themes_defs"}
exec(_src[: _src.index("sessions=sessions_of(")], _ns)  # definitions only, not the analysis
TH.__dict__.update(_ns)

SRC, DATA = sys.argv[1:3]
t0 = time.time()
sessions = sessions_of(READERS["openhands"](Path(SRC), "sqlglot"))
print("read", round(time.time() - t0, 1), "s", len(sessions), "sessions")
ACTIONS = (Kind.COMMAND, Kind.EDIT, Kind.READ, Kind.AGENT_TURN)


INVOCATION = {"exit 4", "exit 5", "FileNotFoundError", "ModuleNotFoundError"}


def fix_steps(lesson, by):
    """The resolution's own records: sources are cited, then alongside, then the fix steps."""
    n = len(lesson.resolution)
    return [by[r] for r in lesson.sources[-n:] if r in by] if n else []


def outcome(lesson, by):
    key = lesson.pain_point.signature.key
    if key[0] in ("C-c", "C-d", "C-z"): return "interrupt"
    if key[0] in TH.PROBE: return "probe"
    if lesson.resolution:
        if any(s.kind == Kind.EDIT and s.files and TH.in_repo(s.files[0]) for s in fix_steps(lesson, by)): return "fixed"
        return "corrected" if key[-1] in INVOCATION else "respelled"
    return "never" if (lesson.unresolved_because or "").startswith("no later") else "unclear"


def turns_lost(s):
    """Agent actions between a failure and the next pass of the same program, spans merged."""
    acts = [r for r in s if r.kind in ACTIONS]
    spans = []
    for i, r in enumerate(acts):
        if not TH.failed(r): continue
        prog = normalise_command(r.command or "")[0]
        end = next((j for j in range(i + 1, min(len(acts), i + 16))
                    if acts[j].kind == Kind.COMMAND and acts[j].exit_code == 0
                    and normalise_command(acts[j].command or "")[0] == prog), min(len(acts) - 1, i + 15))
        spans.append((i, end))
    covered = set()
    for a, b in spans: covered.update(range(a, b + 1))
    return len(covered)


def strip_of(s):
    out = []
    for r in s:
        if r.kind == Kind.COMMAND:
            if (r.command or "").startswith("C-"): continue
            k = normalise_command(r.command or "")
            out.append([r.step, "f" if r.exit_code not in (None, 0) else "p", f"{k[0]} {k[1]}"[:44]])
        elif r.kind == Kind.EDIT:
            f = (r.files or ("?",))[0].lstrip("./")
            out.append([r.step, "e" if TH.in_repo(f) else "s", f[:44]])
        elif r.kind == Kind.USER_TURN:
            out.append([r.step, "u", "you"])
    return out


# themes: codebase vocabulary, as in themes.py
by_task = collections.defaultdict(list)
for s in sessions: by_task[s[0].task_id].append(s)
vocab = collections.Counter()
_ID = re.compile(r"(?:def|class)\s+(\w+)|exp\.(\w+)")
for s in sessions:
    for r in s:
        if r.kind == Kind.EDIT and r.files and TH.in_repo(r.files[0]):
            vocab[Path(r.files[0]).stem.lower()] += 1
            for a, b in _ID.findall(r.diff or r.raw or ""):
                for part in (a or b).lower().split("_"):
                    if len(part) >= 4: vocab[part] += 1
VOCAB = {w for w, c in vocab.items() if c >= 5 and w not in TH.GENERIC_WORDS and w not in TH.DOMAIN_STOP
         and w not in TH.STOPWORDS and not w.startswith("test")}
task_terms = {t: TH.terms_of(TH.task_text(ss[0])) & VOCAB for t, ss in by_task.items()}
df = collections.Counter(w for ts in task_terms.values() for w in ts)
theme_words = [w for w, c in df.most_common() if 6 <= c <= 0.3 * len(by_task)]

t1 = time.time()
facts, trap_sessions, trap_occ, trap_fix = [], collections.defaultdict(set), collections.Counter(), {}
for idx, s in enumerate(sessions):
    by = {(r.session_id, r.step): r for r in s}
    pains = [p for p in mine_session(s, {}) if p.signature.signal == Signal.FAILED_COMMAND]
    les = lessons_from(pains, s)
    oc = collections.Counter()
    for l in les:
        o = outcome(l, by); oc[o] += 1
        if o in ("fixed", "corrected"):
            k = l.pain_point.signature.key
            word = next((w for w in l.resolution if w.startswith("edited")), None) if o == "fixed" else "corrected to: " + l.resolution[-1]
            trap_sessions[k].add(idx); trap_occ[k] += 1; trap_fix.setdefault(k, (word or l.resolution[-1])[:110])
    t = s[0].task_id
    facts.append({"themes": sorted(task_terms[t] & set(theme_words[:40])), "patterns": sorted(TH.patterns_of(s)),
                  "struggled": TH.struggled(s), "turns": turns_lost(s), "outcomes": dict(oc)})
print("lessons per session", round(time.time() - t1, 1), "s")

traps = []
for k, sids in trap_sessions.items():
    if len(sids) < 2: continue
    traps.append({"program": k[0], "target": k[1] if len(k) > 2 else "", "broke": k[-1],
                  "sessions": sorted(sids), "occurrences": trap_occ[k], "fix": trap_fix[k]})
traps.sort(key=lambda x: -len(x["sessions"]))

# strips: the densest-burst session for every theme, pattern and theme x pattern cell
def burstiness(i):
    s = sessions[i]
    fails = [r.step for r in s if TH.failed(r)]
    return sum(1 for f in fails if sum(1 for g in fails if f <= g < f + 10) >= 3) * 1000 - abs(len(s) - 150)
want = set()
def best(idxs):
    idxs = [i for i in idxs if 40 <= len(sessions[i]) <= 260]
    return max(idxs, key=burstiness) if idxs else None
groups = [list(range(len(sessions)))]
groups += [[i for i, f in enumerate(facts) if w in f["themes"]] for w in theme_words[:40]]
groups += [[i for i, f in enumerate(facts) if p in f["patterns"]] for p in TH.PATTERNS]
groups += [[i for i, f in enumerate(facts) if w in f["themes"] and p in f["patterns"]] for w in theme_words[:40] for p in TH.PATTERNS]
for g in groups:
    b = best(g)
    if b is not None: want.add(b)
strips = {i: {"task": sessions[i][0].task_id, "steps": strip_of(sessions[i]), "burst": burstiness(i)} for i in want}

d = json.load(open(DATA))
d["click"] = {"facts": facts, "traps": traps, "strips": strips, "minutesPerTurn": MINUTES_PER_TURN,
              "themeWords": theme_words[:40],
              "titles": {w: [TH.title_of(TH.task_text(by_task[t][0])) for t in by_task if w in task_terms[t]][:2] for w in theme_words[:40]}}
json.dump(d, open(DATA, "w"))
print("traps", len(traps), "strips", len(strips), "turns lost", sum(f["turns"] for f in facts), "total", round(time.time() - t0, 1), "s")

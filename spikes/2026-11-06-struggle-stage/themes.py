"""Throwaway: themes (what was attempted) x patterns (how the struggle looks), sqlglot traces."""
import collections, json, re, sys
from pathlib import Path
from symbiont.readers import READERS
from symbiont.records.schema import Kind
from symbiont.miner.mine import sessions_of
from symbiont.miner.commands import normalise_command
from symbiont.core.rule_terms import STOPWORDS, GENERIC_WORDS

SRC, DATA = sys.argv[1:3]
DOMAIN_STOP = set("""sqlglot select query queries sql expected output support supported parse parsed parsing parser
dialect dialects column columns statement statements correctly incorrectly currently example version python
transpile transpiled transpiling generate generated generates generation hello there thanks thank please would
should could however actually seems below above following produce produces produced string strings
true false none null result traceback using uploaded repository workspace description issue tobymao""".split())
PROBE = {"ls","cat","head","tail","find","stat","file","which","pwd","wc","grep","rg"}
PATTERNS = {
 "test_miss":    ("Ran tests that do not exist", "pytest collected nothing or was given a bad path or option (exit 4 or 5)", "lesson: where the tests live"),
 "inline_trial": ("Trial and error in inline scripts", "three or more failing `python -c` or heredoc scripts", "doc or helper: a ready-made repro script"),
 "scratch_debug":("Debugging in scratch files", "eight or more edits to throwaway files outside the codebase", "doc: how to reproduce a bug here"),
 "edit_thrash":  ("Edit thrash", "the same source file edited five or more times", "lesson: the right extension point"),
 "api_misuse":   ("Wrong API after an edit", "AttributeError, TypeError or NameError right after an edit in the codebase", "lesson: the internal API in this area"),
 "probe_miss":   ("Looking in the wrong place", "five or more probes (ls, find, cat, grep) that found nothing", "doc: a map of the repository"),
 "rerun":        ("Re-running instead of fixing", "three or more failures that passed later with no edit between", "nothing to teach: struggle"),
 "never_fixed":  ("Ended still failing", "the last test run of the session failed", "a human look"),
}
def in_repo(f): f=f.lstrip("./"); return f.startswith(("sqlglot/","tests/","docs/")) and f.endswith(".py")
def failed(r): return r.kind==Kind.COMMAND and r.exit_code not in (None,0) and not (r.command or "").startswith("C-")
_ERR=re.compile(r"\b(AttributeError|TypeError|NameError)\b")

def patterns_of(s):
    found=set(); fails=[r for r in s if failed(r)]
    progs=[normalise_command(r.command or "") for r in fails]
    if any(k[0] in ("pytest","unittest") and r.exit_code in (4,5) for k,r in zip(progs,fails)): found.add("test_miss")
    if sum(1 for k,r in zip(progs,fails) if k[0].startswith("python") and k[1] in ("-","")) >= 3: found.add("inline_trial")
    edits=[f.lstrip("./") for r in s if r.kind==Kind.EDIT for f in r.files[:1]]
    if sum(1 for f in edits if not in_repo(f)) >= 8: found.add("scratch_debug")
    c=collections.Counter(f for f in edits if in_repo(f) and f.startswith("sqlglot/"))
    if c and max(c.values()) >= 5: found.add("edit_thrash")
    last_edit=-1
    for r in s:
        if r.kind==Kind.EDIT and r.files and in_repo(r.files[0]): last_edit=r.step
        elif failed(r) and last_edit>=0 and r.step-last_edit<=4 and _ERR.search(r.raw[-600:]): found.add("api_misuse"); break
    if sum(1 for k in progs if k[0] in PROBE) >= 5: found.add("probe_miss")
    cmds=[r for r in s if r.kind in (Kind.COMMAND, Kind.EDIT)]
    for i,r in enumerate(cmds):
        if failed(r):
            k=normalise_command(r.command or "")[:2]
            for nxt in cmds[i+1:i+6]:
                if nxt.kind==Kind.EDIT: break
                if nxt.kind==Kind.COMMAND and nxt.exit_code==0 and normalise_command(nxt.command or "")[:2]==k and nxt.command!=r.command:
                    found.add("rerun_once"); break
    if sum(1 for _ in [0] if "rerun_once" in found) and _reruns(cmds) >= 3: found.add("rerun")
    found.discard("rerun_once")
    tests=[r for r in s if r.kind==Kind.COMMAND and normalise_command(r.command or "")[0] in ("pytest","unittest")]
    if tests and tests[-1].exit_code not in (None,0): found.add("never_fixed")
    return found

def _reruns(cmds):
    n=0
    for i,r in enumerate(cmds):
        if failed(r):
            k=normalise_command(r.command or "")[:2]
            for nxt in cmds[i+1:i+6]:
                if nxt.kind==Kind.EDIT: break
                if nxt.kind==Kind.COMMAND and nxt.exit_code==0 and normalise_command(nxt.command or "")[:2]==k: n+=1; break
    return n

def struggled(s):
    fails=[r.step for r in s if failed(r)]
    return any(sum(1 for g in fails if f<=g<f+10)>=3 for f in fails)

def task_text(s):
    u=next((r.raw for r in s if r.kind==Kind.USER_TURN),"")
    m=re.search(r"<issue_description>(.*?)</issue_description>",u,re.S)
    return (m.group(1) if m else u)[:1500]

def title_of(text):
    return next((l.strip() for l in text.strip().splitlines() if l.strip()), "")[:90]

def terms_of(text):
    text=re.sub(r"```.*?```"," ",text,flags=re.S)  # prose, not the pasted SQL
    words={w.lower() for w in re.findall(r"[A-Za-z][A-Za-z_]{3,}",text)}
    return {w for w in words if w not in STOPWORDS and w not in GENERIC_WORDS and w not in DOMAIN_STOP}

sessions=sessions_of(READERS["openhands"](Path(SRC),"sqlglot"))
by_task=collections.defaultdict(list)
for s in sessions: by_task[s[0].task_id].append(s)
task_terms={t:terms_of(task_text(ss[0])) for t,ss in by_task.items()}
task_title={t:title_of(task_text(ss[0])) for t,ss in by_task.items()}
_ID=re.compile(r"(?:def|class)\s+(\w+)|exp\.(\w+)")
vocab=collections.Counter()
for s_ in sessions:
    for r in s_:
        if r.kind==Kind.EDIT and r.files and in_repo(r.files[0]):
            vocab[Path(r.files[0]).stem.lower()]+=1
            for a,b in _ID.findall(r.diff or r.raw or ""):
                for part in (a or b).lower().split("_"):
                    if len(part)>=4: vocab[part]+=1
VOCAB={w for w,c in vocab.items() if c>=5 and w not in GENERIC_WORDS and w not in DOMAIN_STOP and w not in STOPWORDS and not w.startswith("test")}
task_terms={t:ts & VOCAB for t,ts in task_terms.items()}
df=collections.Counter(w for ts in task_terms.values() for w in ts)
n_tasks=len(by_task)
cands=[w for w,c in df.items() if 6<=c<=0.3*n_tasks]
info=[]
P={id(s):patterns_of(s) for s in sessions}; ST={id(s):struggled(s) for s in sessions}
base=sum(ST.values())/len(sessions)
for w in cands:
    tasks=[t for t,ts in task_terms.items() if w in ts]; ss=[s for t in tasks for s in by_task[t]]
    rate=sum(ST[id(s)] for s in ss)/len(ss)
    pat={p:round(sum(p in P[id(s)] for s in ss)/len(ss),3) for p in PATTERNS}
    info.append({"theme":w,"tasks":len(tasks),"sessions":len(ss),"struggle":round(rate,3),"patterns":pat,
                 "examples":[task_title[t] for t in tasks[:3]]})
# keep themes that are frequent, then the most distinctive struggle (high or low)
info.sort(key=lambda x:-x["tasks"]); top=[x for x in info if x["sessions"]>=60][:40]
top.sort(key=lambda x:-abs(x["struggle"]-base)); top=top[:16]; top.sort(key=lambda x:-x["struggle"])
overall={p:round(sum(p in P[id(s)] for s in sessions)/len(sessions),3) for p in PATTERNS}
d=json.load(open(DATA))
d["themes"]={"baseline":round(base,3),"rows":top,"patterns":[{"id":k,"name":v[0],"means":v[1],"action":v[2],"share":overall[k]} for k,v in PATTERNS.items()]}
json.dump(d,open(DATA,"w"),indent=1)
print("baseline",round(base,3),"themes",len(info)); print({k:overall[k] for k in PATTERNS})
for t in top: print(f'{t["theme"]:14} tasks {t["tasks"]:3} sess {t["sessions"]:4} struggle {t["struggle"]:.2f} | {t["examples"][0][:60]}')

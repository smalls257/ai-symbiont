import collections, sys
from pathlib import Path
from symbiont.readers import READERS
from symbiont.miner.mine import sessions_of, mine_history
from symbiont.miner.lessons import lessons_from
from symbiont.miner.painpoint import Signal
from symbiont.miner.commands import normalise_command
recs=list(READERS["openhands"](Path(sys.argv[1]),"sqlglot"))
by={(r.session_id,r.step):r for r in recs}
ss=sessions_of(recs)[:600]
sub=[r for s in ss for r in s]
L=[l for l in lessons_from(mine_history(ss,{}),sub) if l.pain_point.signature.signal==Signal.FAILED_COMMAND]
c=collections.Counter()
for l in L:
    if not l.resolution: c["unresolved: "+(l.unresolved_because or "?")[:45]]+=1; continue
    steps=[by[ref] for ref in l.sources[1:]]
    edits=[s for s in steps if s.kind.value!="command"]
    if edits: c["resolved with an edit"]+=1
    elif len(l.resolution)==1: c["resolved: only the later pass"]+=1
    else: c["resolved: other commands, no edit"]+=1
n=len(L); print(n,"failed-command lessons (600 sessions)")
for k,v in c.most_common(): print(f"{v:6d} {v/n:5.0%} {k}")

"""Throwaway: how often do mined pain points recur across sessions/tasks? Counts only."""
import sys, time, collections, json, os
from pathlib import Path
from symbiont.readers import READERS
from symbiont.miner.mine import sessions_of, mine_history
from symbiont.miner.painpoint import Signal

def bucket(n): return "1" if n==1 else "2" if n==2 else "3-5" if n<=5 else "6+"

def coarse(sig):
    k=sig.key
    if sig.signal==Signal.FAILED_COMMAND:
        return {"current":k, "program+error":(k[0],k[-1]), "program":(k[0],)}
    if sig.signal==Signal.REWORKED_EDIT:
        p=k[0]; return {"current":k, "directory":(os.path.dirname(p),), "extension":(os.path.splitext(p)[1],)}
    return {"current":k}

def measure(label, reader, paths, show_keys, limit=None):
    t=time.time(); records=[]
    for p in paths:
        for i,r in enumerate(READERS[reader](Path(p), label)):
            records.append(r)
    sessions=sessions_of(records)
    if limit: sessions=sessions[:limit]
    task_of={ s[0].session_id: (s[0].task_id or s[0].session_id) for s in sessions if s}
    pains=mine_history(sessions, {})
    out={"label":label,"sessions":len(sessions),"tasks":len(set(task_of.values())),"records":len(records),"pain_points":len(pains),"seconds":round(time.time()-t,1),"signals":{}}
    for sig in (Signal.FAILED_COMMAND, Signal.REWORKED_EDIT):
        ps=[p for p in pains if p.signature.signal==sig]
        res={"occurrences":len(ps)}
        for kname in coarse(ps[0].signature) if ps else []:
            groups=collections.defaultdict(list)
            for p in ps: groups[coarse(p.signature)[kname]].append(p)
            sess_hist=collections.Counter(); task_hist=collections.Counter(); max_in_one=collections.Counter()
            occ_multi_session=0; occ_multi_task=0
            for g in groups.values():
                ss={p.session_id for p in g}; ts={task_of.get(p.session_id, p.session_id) for p in g}
                sess_hist[bucket(len(ss))]+=1; task_hist[bucket(len(ts))]+=1
                per=collections.Counter(p.session_id for p in g); max_in_one[bucket(max(per.values()))]+=1
                if len(ss)>1: occ_multi_session+=len(g)
                if len(ts)>1: occ_multi_task+=len(g)
            top=sorted(groups.items(), key=lambda kv:-len({p.session_id for p in kv[1]}))[:12]
            res[kname]={"groups":len(groups),"groups_by_distinct_sessions":dict(sess_hist),"groups_by_distinct_tasks":dict(task_hist),
                        "groups_by_max_in_one_session":dict(max_in_one),
                        "share_of_occurrences_in_multi_session_groups":round(occ_multi_session/len(ps),3),
                        "share_of_occurrences_in_multi_task_groups":round(occ_multi_task/len(ps),3)}
            if show_keys: res[kname]["top_keys"]=[[list(k),len(g),len({p.session_id for p in g})] for k,g in top]
        out["signals"][sig.value]=res
    print(json.dumps(out,indent=1)); sys.stdout.flush()

if __name__=="__main__":
    cfg=json.loads(sys.argv[1]); measure(**cfg)

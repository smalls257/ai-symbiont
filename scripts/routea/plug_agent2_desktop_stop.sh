#!/bin/bash
# HARD HANDOFF to Core's D2: stop the desktop runner and server, void its in-flight runs, free their claims.
cd ~/work/plug2
kill $(cat desktop-runner.pid) 2>/dev/null; pkill -f "plug_agent2_smoke_one.py.*next-runs" 2>/dev/null
kill $(cat desktop-server.pid) 2>/dev/null; sleep 3; pkill -f "llama-server.*--port 8098" 2>/dev/null
python3 - <<'PY'
import hashlib,json,os
rows=json.load(open('next-rows.json')); done=set()
try:
    for l in open('next-runs/runs.jsonl'):
        r=json.loads(l)
        if r.get('error_kind')!='infra' and 'skipped' not in r: done.add(r['instance_id'])
except FileNotFoundError: pass
freed=0
for row in rows:
    t=row['instance_id']; f='next-runs/claims/'+hashlib.sha256(t.encode()).hexdigest()[:24]
    if t not in done and os.path.exists(f) and open(f).read()=='desktop': os.remove(f); freed+=1
print('claims freed',freed)
PY
ss -ltn | grep -c ':8098 ' ; date -Is

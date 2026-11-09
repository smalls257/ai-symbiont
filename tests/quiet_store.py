"""A mined store whose one session has facts but no incident rows (the shape an old store has)."""

from dataclasses import replace

from record_builders import edit, session, user
from symbiont.records.schema import dump_jsonl, load_jsonl
from symbiont.store.local import Source, Store
from symbiont.store.mining import MiningRules, remine


def mine_a_session_without_failures(tmp_path, store: Store, reader: str = "jsonl"):
    steps = session(user("hello"), edit("a.py"))
    path = tmp_path / "quiet.jsonl"
    with path.open("w") as fh:
        dump_jsonl([replace(r, session_id="s1") for r in steps], fh)
    rules = MiningRules({reader: lambda p, project: iter(list(load_jsonl(p.open())))}, frozenset())
    remine(store, "demo", rules, adding=[Source("demo", reader, str(path))])

"""Code-fix lessons study: reading public SWE-smith trajectories (Hugging Face) into steps.

Usage: uv run --with duckdb python scripts/routea/plug_r4_smith_read.py download --repos R.json \
Usage:   --out DIR

Keeps code-running commands (with the last lines of output) and code edits (with their path).
A command failed when its output names an error (SWE-smith observations carry no exit code).
The data stays in DIR, never committed.
"""

import argparse
import json
import re
from pathlib import Path

RUN_PROGRAMS = frozenset(
    {"python", "python3", "pytest", "py.test", "pip", "pip3", "tox", "make", "mypy", "ruff", "uv"}
)
XML_COMMAND = re.compile(r"<function=bash>\s*<parameter=command>(.*?)</parameter>", re.S)
FENCE = re.compile(r"```(?:bash)?\n(.*?)\n```", re.S)
OUTPUT_LINES = 14
SPLITS = ("tool", "xml", "ticks")


def text_of(content) -> str:
    """A message's text, whether content is a string or a list of typed parts."""
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content or ""


def runs_code(command: str) -> bool:
    """True when the command's first word (after any `cd x &&`) is a code-running program."""
    tail = re.sub(r"^\s*cd\s+\S+\s*&&\s*", "", command).strip()
    words = tail.split()
    return bool(words) and words[0].split("/")[-1] in RUN_PROGRAMS


def command_of(message: dict, split: str) -> str | None:
    """The bash command an assistant message issues in this split's format, or None."""
    if split == "tool":
        for call in message.get("tool_calls") or []:
            if call["function"]["name"] == "bash":
                return json.loads(call["function"]["arguments"]).get("command")
        return None
    body = text_of(message.get("content"))
    found = XML_COMMAND.findall(body) if split == "xml" else FENCE.findall(body)
    return found[-1].strip() if found else None


def observation_tail(message: dict) -> str:
    """The last OUTPUT_LINES lines of an observation."""
    body = text_of(message.get("content")).removeprefix("OBSERVATION:").strip("\n")
    return "\n".join(body.splitlines()[-OUTPUT_LINES:])


EDIT_COMMANDS = frozenset({"str_replace", "insert", "create"})
XML_EDITOR = re.compile(r"<function=str_replace_editor>(.*?)</function>", re.S)
XML_PARAM = re.compile(r"<parameter=(\w+)>(.*?)</parameter>", re.S)


def _tool_edit(message: dict) -> str | None:
    for call in message.get("tool_calls") or []:
        if call["function"]["name"] == "str_replace_editor":
            args = json.loads(call["function"]["arguments"])
            return args.get("path") if args.get("command") in EDIT_COMMANDS else None
    return None


def _xml_edit(body: str) -> str | None:
    found = XML_EDITOR.search(body)
    args = dict(XML_PARAM.findall(found.group(1))) if found else {}
    editing = args.get("command", "").strip() in EDIT_COMMANDS
    return args.get("path", "").strip() if editing else None


def _ticks_edit(body: str) -> str | None:
    fenced = FENCE.findall(body)
    words = fenced[-1].split() if fenced else []
    ok = len(words) > 2 and words[0] == "str_replace_editor" and words[1] in EDIT_COMMANDS
    return words[2] if ok else None


def edit_path(message: dict, split: str) -> str | None:
    """The file a str_replace_editor edit (str_replace, insert, create) touches, else None."""
    if split == "tool":
        return _tool_edit(message)
    body = text_of(message.get("content"))
    return _xml_edit(body) if split == "xml" else _ticks_edit(body)


def steps_of(messages: list[dict], split: str) -> list[dict]:
    """Code-running commands (with output tail) and code edits (with path), in order."""
    steps = []
    for index, message in enumerate(messages[:-1]):
        if message["role"] != "assistant":
            continue
        path = edit_path(message, split)
        command = command_of(message, split)
        if path:
            steps.append({"kind": "edit", "path": path})
        elif command and runs_code(command):
            steps.append(
                {"kind": "run", "command": command, "output": observation_tail(messages[index + 1])}
            )
    return steps


def row_of(fields: tuple, split: str) -> dict:
    """One trajectory (instance, traj, model, resolved, messages) as a compact JSON row."""
    instance, traj, model, resolved, messages = fields
    return {
        "instance_id": instance,
        "traj_id": traj,
        "model": model,
        "split": split,
        "resolved": bool(resolved),
        "steps": steps_of(json.loads(messages), split),
    }


def stream_split(con, split: str, marks: str, out: Path) -> dict:
    """Write one split's wanted repositories' rows to per-repo JSONL; the rows per repository."""
    source = f"hf://datasets/SWE-bench/SWE-smith-trajectories/data/{split}-*.parquet"
    query = (
        "select instance_id, traj_id, model, resolved, messages from read_parquet(?) "
        f"where regexp_extract(instance_id,'^(.+?)\\.[0-9a-f]{{8}}\\.',1) in ({marks})"
    )
    cursor = con.execute(query, [source])
    counts: dict[str, int] = {}
    while rows := cursor.fetchmany(200):
        for fields in rows:
            repo = re.match(r"^(.+?)\.[0-9a-f]{8}\.", fields[0]).group(1)
            with (out / f"{repo}.jsonl").open("a") as sink:
                sink.write(json.dumps(row_of(fields, split)) + "\n")
            counts[repo] = counts.get(repo, 0) + 1
    return counts


def download(repos: set[str], out: Path) -> dict:
    """Stream the wanted repositories' trajectories from the three splits into per-repo JSONL."""
    import duckdb  # noqa: PLC0415

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    out.mkdir(parents=True, exist_ok=True)
    marks = ",".join(f"'{r}'" for r in sorted(repos))
    counts: dict[str, int] = {}
    for split in SPLITS:
        for repo, number in stream_split(con, split, marks, out).items():
            counts[repo] = counts.get(repo, 0) + number
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=("download",))
    parser.add_argument("--repos", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(download(set(json.loads(args.repos.read_text())), args.out)))


if __name__ == "__main__":
    main()

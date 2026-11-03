"""A Claude Code session log as the reader parses it, placed where `session_logs` looks."""

import json
import re
from pathlib import Path

IMPORT = "File \"app/parser.py\", line 1\nImportError: cannot import name 'parse'"


def install_claude_session(home: Path, repo: Path, text: str, name: str = "one") -> None:
    """Write `text` as a session of `repo` under `home/.claude/projects`."""
    folder = home / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(repo.resolve()))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.jsonl").write_text(text)


def claude_log():
    """Claude Code JSONL for the three steps: a failing Bash call, an edit, a passing call."""

    def call(id_, name, arguments):
        return {
            "type": "assistant",
            "sessionId": "s1",
            "message": {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": id_, "name": name, "input": arguments}],
            },
        }

    def result(id_, text, error=False):
        return {
            "type": "user",
            "sessionId": "s1",
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": id_, "content": text, "is_error": error}
                ],
            },
        }

    events = [
        call("a", "Bash", {"command": "pytest tests/test_parser.py"}),
        result("a", "Exit code 1\n" + IMPORT, error=True),
        call(
            "b",
            "Edit",
            {"file_path": "app/parser.py", "old_string": "a", "new_string": "def parse(text):"},
        ),
        result("b", "ok"),
        call("c", "Bash", {"command": "pytest tests/test_parser.py"}),
        result("c", "1 passed"),
    ]
    return "\n".join(json.dumps(event) for event in events) + "\n"

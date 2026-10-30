"""QG-SEC-04 published json holds counts, ids and labels only.

Violation prevented: Leaky Narrative at the repo boundary. A results file that carries a
prompt, a patch, a trajectory or any real person's sentence publishes private text or a scored
task's gold answer, and a published string cannot be un-published. A blocklist of key names
(prompt, content, ...) is never complete, so the check allows SHAPES instead:

  * the document is a json object (a bare string or list at the top is refused),
  * every value is a number, a boolean, null, a list or an object, or a string of at most
    MAX_STRING_CHARS characters, no newline and at most MAX_WORDS words,
  * a string with no whitespace at all (a per-step 0/1 flag string, an id, a hash) may run to
    MAX_TOKEN_CHARS: it cannot be a sentence,
  * only a LONG LABEL FIELD (below) may hold a longer sentence, up to MAX_LABEL_CHARS, still with
    no newline, and at most MAX_LONG_LABELS such strings per file; the short label fields (label,
    status, source) keep the 120-character limit and only waive the word count,
  * object keys obey the same length and newline limits,
  * a key that usually carries text (prompt, content, messages, patch, trajectory,
    problem_statement, response, output, ...) is refused when its value is a list, an object or a
    string with spaces; a number or a one-word setting ("reasoning": "low") is not text.

The label fields are the keys the results exporters use for author-written prose: label (a row's
name), status, source; and, long: rule (the stated decision rule), note / notes / any *_note (a
one-line caveat), table / table_rows (rendered result-table lines), caveats, follow_up and result
(the author's own measured statement). They never hold a record's text. Adding a key here is a
gate change.

Usage: check_results_content.py [FILE.json ...]
Default: every tracked or staged results/*.json and dashboard/sample/*.json.
Exit 1 on a finding, 2 if a file cannot be read (a file not judged is a failure, not a pass).
"""

import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

MAX_STRING_CHARS = 120  # an id, a task name, a timestamp, a commit hash, a short label
MAX_WORDS = (
    12  # twelve words is a label; a sentence of real text is longer or sits under another key
)
MAX_LABEL_CHARS = 260  # longest rule or table line measured in results/ is 250
MAX_LONG_LABELS = 40  # strings that need the long-label allowance, per file (measured: 32)
MAX_TOKEN_CHARS = 400  # longest 0/1 per-step flag string measured in results/ is under 200
# Short label fields name a row or a state: the default length limit applies, only the word count
# is waived ("under test, seed-averaged over wiring seeds 0-2 (the row the G6 rule uses)").
SHORT_LABEL_FIELDS = frozenset({"label", "status", "source"})
# Long label fields hold the author's own measured statements, up to MAX_LABEL_CHARS each.
LONG_LABEL_FIELDS = frozenset(
    {"rule", "note", "notes", "table", "table_rows", "caveats", "follow_up", "result"}
)
FORBIDDEN_KEYS = frozenset(
    {
        "prompt",
        "prompts",
        "content",
        "contents",
        "message",
        "messages",
        "patch",
        "trajectory",
        "trajectories",
        "transcript",
        "transcripts",
        "completion",
        "completions",
        "diff",
        "text",
        "body",
        "raw",
        "stdout",
        "stderr",
        "observation",
        "observations",
        "problem_statement",
        "statement",
        "response",
        "responses",
        "output",
        "outputs",
        "input",
        "inputs",
        "reply",
        "replies",
        "summary",
        "comment",
        "comments",
        "command",
        "commands",
        "question",
        "answer",
        "query",
        "instruction",
        "instructions",
        "description",
        "explanation",
        "thought",
        "thoughts",
        "trace",
    }
)
DEFAULT_GLOBS = ("results/*.json", "dashboard/sample/*.json")


def walk(node: object, path: str = "", label: str = "") -> Iterator[tuple[str, str, object, bool]]:
    """Yield (path, enclosing key, value, is_object_member) for every node below `node`."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield f"{path}.{key}", str(key), value, True
            yield from walk(value, f"{path}.{key}", str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield f"{path}[{index}]", label, value, False
            yield from walk(value, f"{path}[{index}]", label)


def is_short_label_field(key: str) -> bool:
    return key.lower() in SHORT_LABEL_FIELDS


def is_long_label_field(key: str) -> bool:
    return key.lower() in LONG_LABEL_FIELDS or key.lower().endswith("_note")


def _limit_for(key: str, text: str) -> int:
    if is_long_label_field(key):
        return MAX_LABEL_CHARS
    return MAX_TOKEN_CHARS if not any(ch.isspace() for ch in text) else MAX_STRING_CHARS


def needs_long_label_allowance(key: str, text: str) -> bool:
    """True when the string is only legal because its key is a long label field."""
    if not is_long_label_field(key):
        return False
    return len(text) > MAX_STRING_CHARS or len(text.split()) > MAX_WORDS


def _string_problems(where: str, key: str, text: str) -> list[str]:
    limit = _limit_for(key, text)
    words_waived = is_long_label_field(key) or is_short_label_field(key)
    problems = []
    if "\n" in text or "\r" in text:
        problems.append(f"{where}: string with a newline; counts and labels only")
    if len(text) > limit:
        problems.append(
            f"{where}: string of {len(text)} chars (limit {limit}); counts and labels only"
        )
    if len(text.split()) > MAX_WORDS and not words_waived:
        problems.append(
            f"{where}: {len(text.split())} words under {key!r}; only label fields hold sentences"
        )
    return problems


def _is_text_like(value: object) -> bool:
    if isinstance(value, str):
        return any(ch.isspace() for ch in value)
    return isinstance(value, (list, dict))


def findings_in(name: str, document: object) -> list[str]:
    if not isinstance(document, dict):
        return [
            f"{name}: top level is {type(document).__name__}, not an object of counts and labels"
        ]
    found = []
    long_labels = 0
    for where, key, value, is_member in walk(document):
        at = f"{name}{where}"
        if is_member and key.lower() in FORBIDDEN_KEYS and _is_text_like(value):
            found.append(f"{at}: field {key!r} holds text, not a count or label (Leaky Narrative)")
        if is_member:
            found += [p.replace(f"{at}:", f"{at} (key):", 1) for p in _string_problems(at, "", key)]
        if isinstance(value, str):
            found += _string_problems(at, key, value)
            long_labels += needs_long_label_allowance(key, value)
    if long_labels > MAX_LONG_LABELS:
        found.append(
            f"{name}: {long_labels} sentence-length strings (limit {MAX_LONG_LABELS}); "
            "a results file is counts and labels, not a report"
        )
    return found


def default_files(root: Path) -> list[Path]:
    """Tracked and staged files only: an untracked scratch file is judged when it is staged."""
    names: set[str] = set()
    for command in (
        ["ls-files", "-z", "--", *DEFAULT_GLOBS],
        ["diff", "--cached", "--name-only", "-z", "--", *DEFAULT_GLOBS],
    ):
        out = subprocess.run(
            ["git", "-C", str(root), *command], capture_output=True, check=True
        ).stdout
        names.update(n for n in out.decode("utf-8", errors="surrogateescape").split("\0") if n)
    return sorted(root / name for name in names if (root / name).is_file())


def main(argv: list[str], root: Path) -> int:
    files = [Path(a) for a in argv] or default_files(root)
    problems = []
    for path in files:
        try:
            problems += findings_in(path.name, json.loads(path.read_text()))
        except (OSError, ValueError) as error:
            print(f"QG-SEC-04: cannot read {path}: {error}", file=sys.stderr)
            return 2
    for line in problems:
        print(f"QG-SEC-04: {line}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], Path(__file__).resolve().parents[2]))

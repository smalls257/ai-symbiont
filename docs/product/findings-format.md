# Lesson findings format

Symbiont can start with lessons another tool already found. Any tool (a code reviewer, a linter
report, a retrospective script) can write them in this format; symbiont does not care which tool
wrote a file.

## Where files live

- `<repo>/.symbiont/findings/*.jsonl` is imported automatically by `symbiont mine` (skip it with
  `--no-findings`).
- Any other file or folder is imported with `symbiont mine --findings PATH`.
- `count_findings(repo)` in `symbiont.readers.findings` counts a repository's findings, for an
  onboarding question such as "Found some lesson findings from other tools, import them?".

## The format

JSON Lines: one finding per line, UTF-8, no blank lines.

| Key | Required | Meaning |
|---|---|---|
| `kind` | yes | `mistake`, `friction`, `correction`, `risk` or `lesson` |
| `text` | yes | The lesson in plain sentences, as you would tell a colleague. No scores. |
| `files` | no | List of repository-relative paths the finding is about |
| `severity` | no | `low`, `medium` or `high` |
| `source` | no | Free-form name of the tool that wrote it |
| `date` | no | ISO-8601 date or date-time |
| `id` | no | Any stable identifier, kept for the writer's own bookkeeping |

An unknown key, a bad value or a line that is not a JSON object stops the import with an error
naming the file and line. Nothing is skipped silently.

## Example

```json
{"kind": "mistake", "text": "The retry helper returned None after the last attempt, so callers saw success.", "files": ["src/retry.py"], "severity": "high", "source": "example-reviewer", "date": "2026-03-02", "id": "f-1"}
{"kind": "friction", "text": "The test command needed an undocumented environment variable."}
```

## Privacy

Imported findings are treated as private: they never reach a Spark-bound prompt.
Every finding becomes a correction-style pain point, so the note reads as "you were corrected on"
followed by the first words of `text`.

"""Which sessions were already asked to reflect, kept beside the store.

A session is asked at most once, and the Stop hook is a fresh process every time, so the memory
has to be a file. One JSON file per data directory, rewritten atomically.
"""

import json
import os
from pathlib import Path

REFLECTIONS_FILE = "reflections.json"
# Older session ids can no longer reach a Stop hook, so only the newest are kept.
KEPT_PER_PROJECT = 200


class ReflectionLedgerError(ValueError):
    """The ledger file exists but is not a ledger; the message names the file."""


class ReflectionLedger:
    """The sessions asked to reflect, per repository, read fresh on every call."""

    def __init__(self, data_dir: Path) -> None:
        """Keep the ledger in `data_dir`; nothing is written until a session is marked."""
        self._path = data_dir / REFLECTIONS_FILE

    def asked(self, project: str, session_id: str) -> bool:
        """Whether this session of `project` was already asked to reflect."""
        return session_id in self._document().get(project, [])

    def mark_asked(self, project: str, session_id: str) -> None:
        """Remember the ask, dropping the oldest ids beyond KEPT_PER_PROJECT."""
        document = self._document()
        document[project] = [*document.get(project, []), session_id][-KEPT_PER_PROJECT:]
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
        os.replace(temporary, self._path)

    def _document(self) -> dict[str, list[str]]:
        """The file's JSON; a missing file is an empty ledger, a malformed one raises."""
        if not self._path.exists():
            return {}
        try:
            document = json.loads(self._path.read_text(encoding="utf-8"))
            if not all(isinstance(ids, list) for ids in document.values()):
                raise TypeError("every project must map to a list of session ids")
        except (ValueError, TypeError, AttributeError) as exc:
            raise ReflectionLedgerError(f"{self._path} is not a reflection ledger") from exc
        return document

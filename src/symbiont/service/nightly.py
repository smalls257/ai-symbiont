"""Per-repository nightly judges: the continuous loop's read side (plug round 4 nightly arm).

Layout under `--nightly-dir`: `<project>/nightly.json` written by `scripts/routea/nightly_record.py`
only after a training run succeeded: {"lessons_digest", "judge_url"}. No record means the
repository has not had its first night: the agree rule applies, and that is logged. A record whose
digest differs from today's lessons is stale, one whose server is down is offline: both raise
(503), because a silent fallback to another rule would change what the user is told.
"""

import hashlib
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from symbiont.egress.client import Transport
from symbiont.miner.lessons import Lesson
from symbiont.service.judge_model import JudgeModel, JudgeOfflineError

log = logging.getLogger(__name__)
RECORD = "nightly.json"


class NightlyStaleError(JudgeOfflineError):
    """The repository's nightly adapter was trained on other lessons than the store holds now."""


def lessons_digest(lessons: Sequence[Lesson]) -> str:
    """A stable hash of which pain points the lessons come from (order-independent)."""
    refs = sorted(
        f"{ref[0]}:{ref[1]}" for lesson in lessons for ref in lesson.pain_point.record_refs
    )
    return hashlib.sha256("\n".join(refs).encode()).hexdigest()


@dataclass(frozen=True)
class NightlyJudges:
    """Where each repository's nightly record lives."""

    root: Path
    # None sends through urllib; tests pass a fake that never opens a socket.
    transport: Transport | None = None

    def judge_for(self, project: str, lessons: Sequence[Lesson]) -> JudgeModel | None:
        """The project's nightly judge, or None before its first night (logged).

        Raises NightlyStaleError when the adapter was trained on other lessons, and
        JudgeOfflineError when the record is unreadable.
        """
        path = self.root / project / RECORD
        if not path.is_file():
            log.warning("recall for %s: no nightly adapter yet, using the agree rule", project)
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            trained, url = record["lessons_digest"], record["judge_url"]
        except (OSError, ValueError, KeyError, TypeError) as unusable:
            raise JudgeOfflineError(f"nightly record {path} is unusable: {unusable}") from unusable
        if trained != lessons_digest(lessons):
            raise NightlyStaleError(
                f"the nightly adapter for {project} is stale: run scripts/routea/nightly_record.py"
            )
        return JudgeModel(url, self.transport)


@dataclass(frozen=True)
class RecallJudges:
    """The judges /recall may use: the three-seed first-night servers and the nightly records."""

    first_night: JudgeModel | None = None
    nightly: NightlyJudges | None = None

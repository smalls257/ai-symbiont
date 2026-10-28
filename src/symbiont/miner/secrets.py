"""Scrub credentials out of lesson text before any Spark-bound use.

Violation this shape prevents: Silent Fallback at the publish boundary. A lesson quotes real
commands and output; a token pasted into a command must not ride a lesson into a Spark-bound
prompt or into the weights of an adapter that answers Spark. The patterns mirror the repo's
gitleaks rules (`.gitleaks.toml`) plus common provider token shapes. Pure: text in, text out.
"""

import re
from dataclasses import replace

from symbiont.miner.lessons import Lesson
from symbiont.miner.painpoint import PainPoint, Signature

REDACTED = "[secret]"
_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)",
        r"\bAKIA[0-9A-Z]{16}\b",  # AWS access key id
        r"\bgh[pousr]_[A-Za-z0-9]{30,}\b",  # GitHub tokens
        r"\bgithub_pat_[A-Za-z0-9_]{30,}\b",
        r"\bhf_[A-Za-z0-9]{30,}\b",  # Hugging Face
        r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}\b",  # OpenAI / Anthropic style
        r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b",  # Slack
        r"\bAIza[0-9A-Za-z_-]{35}\b",  # Google API key
        r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}",
        r"(?i)(?<=://)[^/\s:@]+:[^/\s@]+(?=@)",  # user:password in a URL
        # a value assigned to anything named like a credential (the Meta key rule, generalized)
        r"(?i)(?:api[_-]?key|token|secret|passw(?:or)?d)[\"']?\s*[=:]\s*[\"']?[^\s\"']{8,}",
    )
)


def scrub(text: str) -> str:
    """`text` with every credential-shaped span replaced by REDACTED."""
    for pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def scrubbed(lesson: Lesson) -> Lesson:
    """The lesson with every text field scrubbed, its signature key included."""
    pain = lesson.pain_point
    key = tuple(scrub(part) for part in pain.signature.key)
    unresolved = lesson.unresolved_because
    return replace(
        lesson,
        pain_point=PainPoint(
            Signature(pain.signature.signal, key), pain.session_id, pain.step, pain.record_refs
        ),
        quote=scrub(lesson.quote),
        resolution=tuple(scrub(step) for step in lesson.resolution),
        unresolved_because=None if unresolved is None else scrub(unresolved),
        changed_alongside=tuple(scrub(step) for step in lesson.changed_alongside),
    )

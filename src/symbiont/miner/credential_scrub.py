"""Credential scrubbing for text that is about to be quoted: a pure function, no lesson needed.

Lives apart from `secrets.py` so the failure excerpts the miner cuts (`failure_excerpt.py`) can be
scrubbed where they are cut: `secrets.py` imports `lessons`, which imports the excerpt cutter.
The patterns mirror `.gitleaks.toml` plus common provider token shapes. Text in, text out.
"""

import re

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

"""The credential shapes and the one function that replaces them: a leaf, so any module may scrub.

The patterns mirror `.gitleaks.toml` plus common provider token shapes. A home directory names
its user, which gitleaks flags too, so it becomes `~`. Pure: text in, text out.
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
HOME = "~"
_HOME_DIR = re.compile(r"(?<![\w.~/-])/(?:Users|home)/[A-Za-z0-9._-]+")
# Claude Code spells a project's path with dashes: `~/.claude/projects/-Users-<name>-Code-app`.
_DASHED_HOME_DIR = re.compile(r"(?<=/)-(?:Users|home)-[A-Za-z0-9_.]+(?=[-/]|$)")


def scrub(text: str) -> str:
    """`text` with every credential-shaped span replaced by REDACTED and home directories by ~."""
    for pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    return _DASHED_HOME_DIR.sub(f"-{HOME}", _HOME_DIR.sub(HOME, text))

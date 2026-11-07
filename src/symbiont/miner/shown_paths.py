"""Paths as a teammate reads them: repo-relative, else the file name, never a home directory.

A card says `.git/index.lock` or `identity.controller.ts`, not `/Users/<name>/Code/<repo>/...`.
The user name in a home path is private, and the prefix is noise. Pure: text in, text out.
"""

import re

# An absolute path of two or more parts, not the tail of a URL or a longer word.
_ABSOLUTE = re.compile(r"(?<![\w:/.~-])(?:~|/)(?:[\w.@+-]+/)*[\w.@+-]+")


def plain_paths(text: str, repo_names: frozenset[str] = frozenset()) -> str:
    """`text` with every absolute path cut to its repo-relative part, else its file name."""
    return _ABSOLUTE.sub(lambda found: _plain(found.group(0), repo_names), text)


def _plain(path: str, repo_names: frozenset[str]) -> str:
    parts = path.split("/")
    if len(parts) < 3 and not path.startswith("~"):
        return path
    inside = [i for i, part in enumerate(parts[:-1]) if part in repo_names]
    below = "/".join(parts[inside[0] + 1 :]) if inside else ""
    return below or parts[-1]

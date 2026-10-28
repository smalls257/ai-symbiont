"""The egress allowlist in .semgrep/symbiont/egress.yaml is recomputed here from the standard
library, so a Python upgrade or a hand edit cannot quietly widen it (Distributed Monolith: the
one door can be walked around by an import nobody listed)."""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RULES = (REPO / ".semgrep" / "symbiont" / "egress.yaml").read_text()

# Network, process-plumbing and FFI modules that stay out of the allowed set.
BANNED_STDLIB = {
    "socket", "ssl", "http", "urllib", "asyncio", "ftplib", "smtplib", "poplib", "imaplib",
    "nntplib", "telnetlib", "xmlrpc", "socketserver", "selectors", "select", "webbrowser",
    "wsgiref", "smtpd", "cgi", "cgitb", "imp", "multiprocessing", "ctypes", "asyncore",
    "asynchat", "pip", "ensurepip",
}  # fmt: skip
PROJECT_AND_DEPENDENCIES = {"symbiont", "numpy", "vizdoom"}


def expected_allowed() -> set[str]:
    stdlib = {
        m
        for m in sys.stdlib_module_names
        if (not m.startswith("_") or m == "__future__") and m not in BANNED_STDLIB
    }
    return stdlib | PROJECT_AND_DEPENDENCIES


def _alternations() -> list[set[str]]:
    found = re.findall(
        r"^\s+\^\(\?!(?:\.\*\ import \)\(\?!|\\\.\|)\(\?:((?:[\w\\.]+\|)+[\w\\.]+)\)", RULES, re.M
    )
    return [{name.replace("\\.", ".") for name in alt.split("|")} for alt in found]


def _rule_block(rule_id: str) -> str:
    start = RULES.index(f"  - id: {rule_id}\n")
    nxt = RULES.find("\n  - id: ", start + 1)
    return RULES[start : nxt if nxt != -1 else len(RULES)]


def _path_list(rule_id: str, key: str) -> list[str]:
    match = re.search(rf"^\s+{key}: \[(.*?)\]$", _rule_block(rule_id), re.M)
    return re.findall(r'"([^"]+)"', match.group(1)) if match else []


def _allowed_sets(rule_id: str) -> list[set[str]]:
    found = re.findall(
        r"^\s+\^\(\?!(?:\.\*\ import \)\(\?!|\\\.\|)\(\?:((?:[\w\\.]+\|)+[\w\\.]+)\)",
        _rule_block(rule_id),
        re.M,
    )
    return [{name.replace("\\.", ".") for name in alt.split("|")} for alt in found]


def test_both_import_regexes_carry_exactly_the_expected_allowed_set():
    sets = _allowed_sets("sym-single-egress")
    assert len(sets) == 2, "the import and from-import regexes were not found"
    for found in sets:
        assert found == expected_allowed(), sorted(found ^ expected_allowed())


def test_the_listener_rule_allows_the_same_set_plus_http_server_and_nothing_else():
    sets = _allowed_sets("sym-service-server-transport")
    assert len(sets) == 2
    for found in sets:
        assert found == expected_allowed() | {"http.server"}, sorted(found ^ expected_allowed())


def test_only_the_listener_file_is_excluded_from_the_import_allowlist():
    assert _path_list("sym-single-egress", "exclude") == [
        "/src/symbiont/egress/",
        "/src/symbiont/service/server.py",
    ]
    for rule in ("sym-dynamic-import", "sym-network-subprocess", "sym-subprocess-literal-command"):
        assert _path_list(rule, "exclude") == ["/src/symbiont/egress/"], rule
    assert _path_list("sym-no-prompt-logging", "exclude") == []


def test_the_listener_rule_is_scoped_to_exactly_the_listener_file():
    assert _path_list("sym-service-server-transport", "include") == [
        "/src/symbiont/service/server.py"
    ]
    assert _path_list("sym-service-server-transport", "exclude") == []


def test_no_network_library_is_in_the_allowed_set():
    for name in (
        "requests",
        "httpx",
        "socket",
        "ssl",
        "http",
        "asyncio",
        "grpc",
        "boto3",
        "openai",
    ):
        assert name not in expected_allowed()
    assert "urllib" not in expected_allowed() and "urllib.parse" not in expected_allowed()

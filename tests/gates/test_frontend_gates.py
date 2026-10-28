"""QG-FE-01, QG-FE-02, QG-FE-03: eslint, no external CDN, HTML validity.

Each gate is shown going red on a planted violation and green on a clean page. The CDN policy
is checked by directory, because docs/explainer/ arrives from another branch and must be
covered without a change here."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GATES = REPO / "scripts" / "gates"
sys.path.insert(0, str(GATES))

import check_cdn  # noqa: E402
import check_html_report  # noqa: E402


@pytest.mark.parametrize(
    "path, text",
    [
        ("dashboard/index.html", '<script src="https://cdn.example.com/lib.js"></script>'),
        ("dashboard/index.html", '<link rel="stylesheet"\n  href="//fonts.example.com/a.css">'),
        ("dashboard/style.css", '@import url("https://fonts.example.com/a.css");'),
        ("dashboard/style.css", "body { background: url(http://img.example.com/a.png); }"),
        ("dashboard/app.js", 'const r = await fetch("https://api.example.com/x");'),
        ("dashboard/index.html", '<script src="https://cdn.jsdelivr.net/npm/mermaid"></script>'),
        ("docs/explainer/index.html", '<link href="https://fonts.googleapis.com/css" rel="x">'),
        ("docs/plan/p.html", '<img src="https://tracker.example.com/p.gif">'),
        (
            "docs/explainer/index.html",
            '<script src="https://cdn.jsdelivr.net/npm/mermaid"></script>',
        ),
        ("docs/new/page.html", '<script src="https://cdn.jsdelivr.net/npm/mermaid"></script>'),
    ],
)
def test_an_external_load_is_refused(path, text):
    assert check_cdn.problems_in(path, text), (path, text)


@pytest.mark.parametrize(
    "path, text",
    [
        ("dashboard/index.html", '<script src="app.js"></script><link href="style.css">'),
        ("dashboard/app.js", 'const NS = "http://www.w3.org/2000/svg"; fetch("sample/a.json");'),
        ("dashboard/index.html", '<a href="https://example.com/docs">docs</a>'),
        ("README.md", '<script src="https://cdn.example.com/x.js"></script>'),
    ],
)
def test_local_loads_links_namespaces_and_the_docs_exemption_pass(path, text):
    assert check_cdn.problems_in(path, text) == []


def test_legacy_pages_are_reported_but_a_new_page_with_the_same_load_fails(tmp_path, monkeypatch):
    load = '<script src="https://cdn.jsdelivr.net/npm/mermaid"></script>\n'
    (tmp_path / "docs").mkdir()
    for name in ("old.html", "new.html"):
        (tmp_path / "docs" / name).write_text(load)
    legacy = tmp_path / "legacy.txt"
    legacy.write_text("docs/old.html\n")
    monkeypatch.setattr(check_cdn, "ROOT", tmp_path)
    monkeypatch.setattr(check_cdn, "LEGACY_FILE", legacy)
    assert check_cdn.main(["x", "docs/old.html"]) == 0
    assert check_cdn.main(["x", "docs/new.html"]) == 1


def test_the_reported_line_is_the_line_of_the_tag():
    text = "<p>a</p>\n<p>b</p>\n<script src='https://x.example.com/a.js'></script>\n"
    assert check_cdn.problems_in("dashboard/i.html", text)[0].startswith("dashboard/i.html:3:")


def test_html_validity_counts_errors_not_warnings():
    report = [
        {
            "filePath": "/x/a.html",
            "messages": [
                {"severity": 2, "line": 1, "column": 2, "ruleId": "r", "message": "bad"},
                {"severity": 1, "line": 3, "column": 4, "ruleId": "w", "message": "meh"},
            ],
        }
    ]
    assert check_html_report.errors_in(report) == ["a.html:1:2 r: bad"]


def _node_repo(tmp_path: Path) -> Path:
    tools = REPO / "dashboard" / "node_modules"
    assert tools.is_dir(), "the frontend tools are missing: run `cd dashboard && npm ci`"
    root = tmp_path / "repo"
    (root / "dashboard").mkdir(parents=True)
    shutil.copytree(GATES, root / "scripts/gates", ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("package.json", "eslint.config.js", ".htmlvalidate.mjs"):
        shutil.copy(REPO / "dashboard" / name, root / "dashboard" / name)
    (root / "dashboard/node_modules").symlink_to(tools)
    (root / ".venv").symlink_to(REPO / ".venv")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def _gate(root: Path, script: str, *files: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(root / "scripts/gates" / script), *files],
        cwd=root, capture_output=True, text=True, check=False,
    )  # fmt: skip


@pytest.mark.periphery
def test_loose_equality_and_unused_names_turn_eslint_red(tmp_path):
    root = _node_repo(tmp_path)
    (root / "dashboard/bad.js").write_text("const unused = 1;\nif (a == b) { go(); }\n")
    (root / "dashboard/ok.js").write_text("const total = 1;\ndocument.title = String(total);\n")
    assert _gate(root, "check_js.sh", "dashboard/bad.js").returncode == 1
    assert _gate(root, "check_js.sh", "dashboard/ok.js").returncode == 0


@pytest.mark.periphery
def test_missing_eslint_with_work_to_do_exits_2(tmp_path):
    root = _node_repo(tmp_path)
    (root / "dashboard/node_modules").unlink()
    (root / "dashboard/ok.js").write_text("const total = 1;\ndocument.title = String(total);\n")
    out = _gate(root, "check_js.sh", "dashboard/ok.js")
    assert out.returncode == 2 and "npm ci" in out.stderr


@pytest.mark.periphery
def test_invalid_html_is_reported_and_valid_html_is_clean(tmp_path):
    root = _node_repo(tmp_path)
    valid = (
        '<!doctype html><html lang="en"><head><title>t</title></head><body><p>x</p></body></html>'
    )
    (root / "dashboard/good.html").write_text(valid)
    (root / "dashboard/bad.html").write_text("<html><body><div><p>unclosed</div></body>")
    assert _gate(root, "check_html.sh", "dashboard/bad.html").returncode == 1
    assert _gate(root, "check_html.sh", "dashboard/good.html").returncode == 0

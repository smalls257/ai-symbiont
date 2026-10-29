"""The import-linter contracts hold on the tree, agree with tests/test_boundaries.py, name
every package, and demonstrably catch a violation (a contract that cannot fail is a Paper
Tiger: include_external_packages silently off would pass forever)."""

import configparser
import subprocess
import sys
from pathlib import Path

import pytest

from import_rules import FORBIDDEN_MODULES

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / ".importlinter"
LINT_IMPORTS = Path(sys.executable).parent / "lint-imports"

pytestmark = pytest.mark.periphery


def _forbidden_for_core() -> set[str]:
    parser = configparser.ConfigParser(allow_no_value=True)
    parser.read(CONFIG)
    section = parser["importlinter:contract:core-passes-the-airplane-test"]
    return {m.strip() for m in section["forbidden_modules"].split() if m.strip()}


def test_contracts_hold_on_the_tree():
    out = subprocess.run([str(LINT_IMPORTS)], cwd=REPO, capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "0 broken" in out.stdout


def test_contract_covers_every_module_the_boundary_test_forbids():
    contract = _forbidden_for_core() | {m.removesuffix(".**") for m in _forbidden_for_core()}
    assert set(FORBIDDEN_MODULES) <= contract


def test_every_package_under_src_is_named_in_the_config():
    config_text = CONFIG.read_text()
    src = REPO / "src" / "symbiont"
    packages = [p.name for p in src.iterdir() if p.is_dir() and (p / "__init__.py").exists()]
    modules = [p.stem for p in src.glob("*.py") if p.stem not in ("__init__", "__main__")]
    missing = [n for n in packages + modules if f"symbiont.{n}" not in config_text]
    # core, miner and records are listed in the layers contract; the rest are forbidden or sources.
    assert missing == [], f"add these to .importlinter: {missing}"


def test_a_core_module_importing_sqlite3_breaks_the_contract(tmp_path):
    pkg = tmp_path / "symbiont"
    (pkg / "core").mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "core" / "__init__.py").write_text("")
    (pkg / "core" / "leaky.py").write_text("import sqlite3\n")
    config = tmp_path / ".importlinter"
    config.write_text(
        "[importlinter]\nroot_packages =\n    symbiont\ninclude_external_packages = True\n"
        "[importlinter:contract:c]\nname = pure\ntype = forbidden\n"
        "source_modules =\n    symbiont.core\nforbidden_modules =\n    sqlite3\n"
    )
    out = subprocess.run(
        [str(LINT_IMPORTS), "--config", str(config)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode != 0
    assert "BROKEN" in out.stdout


def _network_contract_section() -> str:
    text = CONFIG.read_text()
    start = text.index("[importlinter:contract:network-only-through-egress]")
    return text[start : text.index("\n[importlinter:contract:", start + 1)]


def _only_act1_as_source(section: str) -> str:
    """The real contract names every package; the tiny tree here has only act1 and egress."""
    head, rest = section.split("source_modules =\n", 1)
    kept = rest[rest.index("forbidden_modules") :]
    # The tiny tree has no listener module, and an unmatched exception is an error by design.
    kept = kept.split("ignore_imports =")[0]
    return head + "source_modules =\n    symbiont.act1\n" + kept


def _run_linter_on(tmp_path: Path, body_of_act1_module: str) -> subprocess.CompletedProcess:
    """The repo's own network contract, run on a tiny tree whose act1 module has the given body."""
    for package in ("act1", "egress"):
        (tmp_path / "symbiont" / package).mkdir(parents=True)
        (tmp_path / "symbiont" / package / "__init__.py").write_text("")
    (tmp_path / "symbiont" / "__init__.py").write_text("")
    (tmp_path / "symbiont" / "egress" / "client.py").write_text("import urllib.request\n")
    (tmp_path / "symbiont" / "act1" / "reach.py").write_text(body_of_act1_module)
    config = tmp_path / ".importlinter"
    config.write_text(
        "[importlinter]\nroot_packages =\n    symbiont\ninclude_external_packages = True\n"
        + _only_act1_as_source(_network_contract_section())
    )
    return subprocess.run(
        [str(LINT_IMPORTS), "--config", str(config)],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )  # fmt: skip


def test_a_direct_network_import_outside_egress_breaks_the_network_contract(tmp_path):
    out = _run_linter_on(tmp_path, "import urllib.request\n")
    assert out.returncode != 0 and "BROKEN" in out.stdout


def test_going_through_egress_keeps_the_network_contract(tmp_path):
    out = _run_linter_on(tmp_path, "from symbiont.egress import client\n")
    assert out.returncode == 0, out.stdout


def test_the_network_contract_excepts_exactly_the_listener():
    section = _network_contract_section()
    ignored = section.split("ignore_imports =", 1)[1].split("\n[", 1)[0]
    lines = [ln.strip() for ln in ignored.splitlines() if ln.strip() and not ln.startswith(";")]
    assert lines == ["symbiont.service.server -> http"]
    assert "unmatched_ignore_imports_alerting" not in section, "the default (error) must stay"

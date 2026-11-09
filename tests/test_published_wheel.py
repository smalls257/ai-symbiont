"""The published wheel is the product alone: no research code, and nothing shipped needs any.

Research and hackathon code (act1, eval, routeb, the remote model door) stays in the repo and is
excluded from the wheel in pyproject.toml. Excluding a file only helps if nothing shipped imports
it: an import of a missing module would break a user's install (Paper Tiger), and a product module
reaching for research code is the coupling this boundary exists to stop (Distributed Monolith).
So the wheel is built for real and every import inside it must resolve inside it.
"""

import ast
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = (
    "symbiont/act1/",
    "symbiont/eval/",
    "symbiont/routeb/",
    "symbiont/egress/lan_send.py",
    "symbiont/egress/remote_send.py",
    "symbiont/egress/remote_chat.py",
    "symbiont/egress/spend.py",
    "symbiont/egress/providers.py",
    "symbiont/egress/credentials.py",
    "symbiont/egress/messages.py",
    "symbiont/egress/file_lock.py",
)
# What a shipped module may import besides itself: the standard library and the one runtime
# dependency. The nightly extra's torch and transformers run in separate scripts, never imported.
ALLOWED_ROOTS = frozenset(sys.stdlib_module_names) | {"symbiont", "numpy"}


@pytest.fixture(scope="module")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> dict[str, bytes]:
    out = tmp_path_factory.mktemp("wheel")
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out), str(ROOT)],
        check=True,
        capture_output=True,
    )
    (built,) = out.glob("*.whl")
    with zipfile.ZipFile(built) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _modules(files: dict[str, bytes]) -> set[str]:
    names = set()
    for path in files:
        if path.endswith(".py"):
            parts = path[: -len(".py")].split("/")
            names.add(".".join(parts[:-1] if parts[-1] == "__init__" else parts))
    return names


def _imports(source: bytes) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
            found |= {f"{node.module}.{alias.name}" for alias in node.names}
    return found


def _unresolved(files: dict[str, bytes]) -> list[str]:
    shipped = _modules(files)
    missing = []
    for path, source in files.items():
        if not path.endswith(".py"):
            continue
        for name in _imports(source):
            root = name.split(".")[0]
            if root != "symbiont":
                if root not in ALLOWED_ROOTS:
                    missing.append(f"{path}: {name} (not stdlib or a runtime dependency)")
                continue
            parent = name.rsplit(".", 1)[0]
            if name not in shipped and parent not in shipped:
                missing.append(f"{path}: {name}")
    return sorted(missing)


@pytest.mark.periphery
def test_the_wheel_ships_no_research_code(wheel):
    leaked = sorted(path for path in wheel if path.startswith(RESEARCH))
    assert leaked == []


@pytest.mark.periphery
def test_every_import_in_the_wheel_resolves_inside_the_wheel(wheel):
    assert _unresolved(wheel) == []


@pytest.mark.periphery
def test_the_wheel_holds_the_commands_the_plugin_runs(wheel):
    for module in (
        "symbiont/cli.py",
        "symbiont/delivery/hook_main.py",
        "symbiont/egress/client.py",
    ):
        assert module in wheel


def test_a_shipped_import_of_research_code_is_caught():
    files = {
        "symbiont/__init__.py": b"",
        "symbiont/service/__init__.py": b"",
        "symbiont/service/x.py": b"from symbiont.egress.remote_chat import RemoteChatSession\n",
    }
    assert _unresolved(files) == [
        "symbiont/service/x.py: symbiont.egress.remote_chat",
        "symbiont/service/x.py: symbiont.egress.remote_chat.RemoteChatSession",
    ]


def test_a_shipped_import_of_an_undeclared_package_is_caught():
    files = {"symbiont/__init__.py": b"import requests\n"}
    assert _unresolved(files) == [
        "symbiont/__init__.py: requests (not stdlib or a runtime dependency)"
    ]

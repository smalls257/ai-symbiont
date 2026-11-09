"""The plugin repo export: product files only, decided by the same list as the wheel."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import export_plugin_repo as export  # noqa: E402

GLOBS = ["src/symbiont/act1", "src/symbiont/egress/remote_send.py", "src/symbiont/**/AGENTS.md"]


@pytest.mark.parametrize(
    "path",
    [
        "src/symbiont/act1/glimmer.py",
        "src/symbiont/act1/assets/map.txt",
        "src/symbiont/egress/remote_send.py",
        "src/symbiont/service/AGENTS.md",
    ],
)
def test_research_paths_are_recognized(path):
    assert export.is_research(path, GLOBS)


@pytest.mark.parametrize(
    "path", ["src/symbiont/egress/client.py", "src/symbiont/act1x.py", "plugin/symbiont/README.md"]
)
def test_product_paths_are_kept(path):
    assert not export.is_research(path, GLOBS)


def test_the_research_list_is_read_from_pyproject():
    globs = export.research_globs((REPO / "pyproject.toml").read_bytes())
    assert "src/symbiont/act1" in globs and "src/symbiont/egress/remote_send.py" in globs


def test_a_research_marker_in_a_product_file_refuses_the_export():
    tree = {"src/symbiont/service/x.py": b"URL = 'https://api.meta.ai/v1'\n"}
    with pytest.raises(export.ExportError, match="service/x.py mentions api.meta.ai"):
        export.check_tree(tree, GLOBS)


def test_the_tree_gets_the_plugin_readme_and_its_origin():
    files = {
        "pyproject.toml": (REPO / "pyproject.toml").read_bytes(),
        "plugin/symbiont/README.md": b"# symbiont plugin\n",
        "src/symbiont/act1/glimmer.py": b"",
        "src/symbiont/cli.py": b"",
    }
    tree = export.product_tree(files, "abc123")
    assert tree["README.md"] == b"# symbiont plugin\n"
    assert tree["EXPORTED_FROM"] == b"https://github.com/smalls257/ai-symbiont abc123\n"
    assert "src/symbiont/act1/glimmer.py" not in tree and "src/symbiont/cli.py" in tree


def _tracked_product_files() -> dict[str, bytes]:
    """The tracked product files as they are on disk: what the next commit will export."""
    listed = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "--", *export.PRODUCT_PATHS],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    return {path: (REPO / path).read_bytes() for path in listed if (REPO / path).is_file()}


@pytest.mark.periphery
def test_the_product_tree_exports_and_passes_its_checks(tmp_path):
    out = tmp_path / "plugin-repo"
    assert export.export_files(_tracked_product_files(), "working-tree", out) > 100
    assert (out / ".claude-plugin" / "marketplace.json").is_file()
    assert (out / "plugin" / "symbiont" / "hooks" / "hooks.json").is_file()
    assert (out / "src" / "symbiont" / "cli.py").is_file()
    assert not (out / "src" / "symbiont" / "act1").exists()
    assert not (out / "scripts").exists() and not (out / "results").exists()


@pytest.mark.periphery
def test_a_committed_ref_yields_only_product_paths():
    files = export.committed_files("HEAD")
    assert "pyproject.toml" in files and "src/symbiont/cli.py" in files
    outside = [path for path in files if not path.startswith(export.PRODUCT_PATHS)]
    assert outside == []


@pytest.mark.periphery
def test_an_existing_output_directory_is_refused(tmp_path):
    assert export.main(["--out", str(tmp_path)]) == 2


def test_every_install_instruction_names_the_plugin_repo():
    tracked = subprocess.run(
        ["git", "-C", str(REPO), "ls-files"], check=True, capture_output=True, text=True
    ).stdout.split()
    stale = [
        path
        for path in tracked
        if not path.startswith(("prereg/", "results/", "tests/scripts/test_export_plugin_repo.py"))
        and (REPO / path).is_file()
        and _names_the_research_repo_as_install((REPO / path).read_bytes())
    ]
    assert stale == []


def _names_the_research_repo_as_install(body: bytes) -> bool:
    text = body.decode(errors="replace")
    for line in text.splitlines():
        install = "install" in line or "marketplace add" in line or "REPO_URL" in line
        research_repo = "github.com/smalls257/ai-symbiont" in line
        if install and research_repo and "ai-symbiont-plugin" not in line:
            return True
    return False

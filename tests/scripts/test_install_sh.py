"""install.sh with fake `uv` and `symbiont` on PATH: no network, no real install."""

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
INSTALL = REPO / "install.sh"
SOURCE = "git+https://github.com/smalls257/ai-symbiont-plugin"


def _script(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def fakes(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    _script(
        bin_dir / "uv",
        f'echo "uv $*" >> "{log}"\n'
        f'if [ "$1 $2 $3" = "tool dir --bin" ]; then echo "{bin_dir}"; fi\n',
    )
    _script(bin_dir / "symbiont", f'echo "symbiont $*" >> "{log}"\n')
    return bin_dir, log


def _run(bin_dir, *args, with_uv=True):
    path = f"{bin_dir}:/usr/bin:/bin" if with_uv else "/usr/bin:/bin"
    return subprocess.run(
        ["sh", str(INSTALL), *args],
        env={"PATH": path, "HOME": str(bin_dir)},
        capture_output=True,
        text=True,
        check=False,
    )


def test_install_sh_installs_the_package_then_runs_setup(fakes):
    bin_dir, log = fakes
    done = _run(bin_dir, "--ref", "v1", "--harness", "none")
    assert done.returncode == 0, done.stderr
    lines = log.read_text().splitlines()
    assert f"uv tool install --force ai-symbiont @ {SOURCE}@v1" in lines
    assert lines.index("uv tool update-shell") > lines.index(
        f"uv tool install --force ai-symbiont @ {SOURCE}@v1"
    )
    assert lines[-1] == "symbiont setup --harness none"


def test_install_sh_defaults_to_main_with_no_extras_and_auto(fakes):
    bin_dir, log = fakes
    assert _run(bin_dir).returncode == 0
    lines = log.read_text().splitlines()
    assert f"uv tool install --force ai-symbiont @ {SOURCE}@main" in lines
    assert lines[-1] == "symbiont setup --harness auto"


def test_install_sh_nightly_adds_the_extra(fakes):
    bin_dir, log = fakes
    assert _run(bin_dir, "--nightly").returncode == 0
    assert f"uv tool install --force ai-symbiont[nightly] @ {SOURCE}@main" in log.read_text()


def test_install_sh_without_uv_says_how_to_get_it_and_exits_1(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    done = _run(empty, with_uv=False)
    assert done.returncode == 1
    assert "https://astral.sh/uv/install.sh" in done.stderr + done.stdout


def test_install_sh_refuses_an_unknown_flag(fakes):
    bin_dir, log = fakes
    done = _run(bin_dir, "--bogus")
    assert done.returncode == 2
    assert not log.exists()


def test_install_sh_twice_is_safe(fakes):
    bin_dir, log = fakes
    assert _run(bin_dir, "--harness", "none").returncode == 0
    assert _run(bin_dir, "--harness", "none").returncode == 0
    installs = [line for line in log.read_text().splitlines() if "tool install" in line]
    assert len(installs) == 2
    assert os.access(INSTALL, os.R_OK)

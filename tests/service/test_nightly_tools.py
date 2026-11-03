"""The real-world edges of the nightly: processes, the Python probe, the judge server call.

Violation prevented: Black Box. A trainer that cannot start, a Python without mlx and a judge
that is down each say what happened and what to do; none returns a quiet success.
"""

import json
import subprocess
import sys

import pytest

from symbiont.service.nightly_backend import Backend
from symbiont.service.nightly_run import NightFailedError
from symbiont.service.nightly_schedule import ScheduleError, Tool
from symbiont.service.nightly_tools import (
    LocalMachine,
    checked_python,
    default_judge_url,
    restart_instructions,
    run_logged,
    told_judge,
)

pytestmark = pytest.mark.periphery
URL = "http://127.0.0.1:8861"


def test_run_logged_returns_the_exit_code_and_keeps_all_output_in_the_log(tmp_path):
    log = tmp_path / "t.log"
    script = "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"
    code = run_logged(sys.executable, ["-c", script], log, {})
    assert code == 3
    assert set(log.read_text().split()) == {"out", "err"}


def test_a_trainer_that_cannot_start_raises_naming_it(tmp_path):
    with pytest.raises(NightFailedError, match="no-such-trainer"):
        run_logged("no-such-trainer", [], tmp_path / "t.log", {})


def test_a_python_without_mlx_is_refused_with_the_install_hint():
    with pytest.raises(NightFailedError, match="mlx-lm"):
        checked_python(sys.executable, Backend.MLX)


def test_a_python_that_does_not_exist_is_refused_before_any_work():
    with pytest.raises(NightFailedError, match="was not found"):
        checked_python("/no/such/python", Backend.MLX)


def test_the_default_judge_url_is_loopback_in_the_nightly_port_range_and_stable():
    url = default_judge_url("owner__repo")
    assert url == default_judge_url("owner__repo")
    port = int(url.rsplit(":", 1)[1])
    assert url.startswith("http://127.0.0.1:") and 8800 <= port < 8900


def test_restart_instructions_name_python_server_base_adapter_and_port(tmp_path):
    text = restart_instructions("/venv/python", URL, tmp_path / "adapter", tmp_path / "base")
    assert text.startswith("/venv/python ")
    assert f"--adapter {tmp_path / 'adapter'}" in text
    assert f"--model {tmp_path / 'base'}" in text
    assert text.endswith("--port 8861")


def test_a_judge_that_confirms_the_adapter_is_reported_live(tmp_path):
    seen = []

    def transport(request, timeout_s):
        seen.append((request.full_url, json.loads(request.data)))
        return json.dumps({"loaded": str(tmp_path / "adapter")}).encode()

    said = told_judge("py", URL, tmp_path / "adapter", tmp_path / "base", transport)
    assert "now serves the new adapter" in said
    assert seen == [(URL + "/reload", {"adapter": str(tmp_path / "adapter")})]


def test_a_judge_that_is_down_gets_the_exact_restart_command_not_silence(tmp_path):
    def down(request, timeout_s):
        raise ConnectionRefusedError

    said = told_judge("py", URL, tmp_path / "adapter", tmp_path / "base", down)
    assert "is not answering" in said
    assert "--port 8861" in said


def test_a_non_loopback_judge_url_is_refused_not_called(tmp_path):
    with pytest.raises(NightFailedError, match="refused"):
        told_judge("py", "http://example.com:80", tmp_path, tmp_path)


def test_the_local_machine_reads_writes_and_deletes_files(tmp_path):
    machine = LocalMachine()
    target = tmp_path / "a" / "b.txt"
    machine.write(target, b"x")
    assert machine.read(target) == b"x"
    machine.delete(target)
    assert machine.read(target) is None


def test_a_scheduler_tool_that_is_not_installed_raises_schedule_error(monkeypatch):
    monkeypatch.setenv("PATH", "")
    with pytest.raises(ScheduleError, match="launchctl"):
        LocalMachine().run(Tool.LAUNCHCTL, ["print", "x"])


def test_the_trainer_python_is_found_by_path_so_the_command_head_stays_a_literal(tmp_path):
    log = tmp_path / "t.log"
    script = "import sys; print(sys.prefix)"
    assert run_logged(sys.executable, ["-c", script], log, {}) == 0
    # A Windows venv's python.exe starts the base interpreter, so its prefix is asked, not assumed.
    expected = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert log.read_text(encoding="utf-8").strip() == expected

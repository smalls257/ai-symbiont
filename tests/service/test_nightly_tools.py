"""The real-world edges of the nightly: processes, the Python probe, the judge server call.

Violation prevented: Black Box. A trainer that cannot start, a Python without mlx and a judge
that is down each say what happened and what to do; none returns a quiet success.
"""

import json
import sys
from pathlib import Path

import pytest

from symbiont.service.judge_start import JudgeStart, JudgeStartError, judge_start_from_json
from symbiont.service.nightly_backend import Backend
from symbiont.service.nightly_run import NightFailedError
from symbiont.service.nightly_schedule import ScheduleError, Tool
from symbiont.service.nightly_tools import (
    LocalMachine,
    checked_python,
    default_judge_url,
    ensured_judge,
    judge_device,
    restart_instructions,
    run_logged,
    spawn_judge,
    told_judge,
    waited_for_judge,
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

    said = told_judge(URL, tmp_path / "adapter", "start-it", transport)
    assert "now serves the new adapter" in said
    assert seen == [(URL + "/reload", {"adapter": str(tmp_path / "adapter")})]


def test_a_judge_that_is_down_gets_the_exact_restart_command_not_silence(tmp_path):
    def down(request, timeout_s):
        raise ConnectionRefusedError

    said = told_judge(URL, tmp_path / "adapter", "start-it", down)
    assert "is not answering" in said
    assert "  start-it\n" in said


def test_a_non_loopback_judge_url_is_refused_not_called(tmp_path):
    with pytest.raises(NightFailedError, match="refused"):
        told_judge("http://example.com:80", tmp_path, "start-it")


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
    printed = log.read_text(encoding="utf-8").strip()
    if sys.platform == "win32":
        # CreateProcess looks in the running executable's directory before PATH, and a venv's
        # python.exe runs the base interpreter, so on Windows only "a Python ran" is guaranteed.
        assert Path(printed).is_dir()
        return
    assert printed == sys.prefix


def test_a_mac_restart_command_carries_mps_and_a_cuda_box_carries_cuda(tmp_path):
    mac = restart_instructions("py", URL, tmp_path / "a", tmp_path / "b", judge_device(Backend.MLX))
    gpu = restart_instructions(
        "py", URL, tmp_path / "a", tmp_path / "b", judge_device(Backend.TORCH_CUDA)
    )
    assert mac.startswith("LCAP_DEVICE=mps py ") and gpu.startswith("py ")


class FakeChild:
    def __init__(self, exit_code=None):
        self.exit_code = exit_code

    def poll(self):
        return self.exit_code

    @property
    def returncode(self):
        return self.exit_code


START = JudgeStart("py", "/base", "/adapter", "mps", 8861)


def judge_that_comes_up_after(refusals):
    state = {"left": refusals}

    def transport(request, timeout_s):
        if request.full_url.endswith("/reload") or state["left"] > 0:
            state["left"] -= 1
            raise ConnectionRefusedError
        return json.dumps({"p_yes": [0.5]}).encode()

    return transport


def test_a_running_judge_is_reloaded_and_nothing_is_started():
    def transport(request, timeout_s):
        return json.dumps({"loaded": "/adapter"}).encode()

    said = ensured_judge(
        START, URL, Path("log"), transport, lambda *_: pytest.fail("started a second server")
    )
    assert "now serves the new adapter" in said


def test_a_judge_that_is_down_is_started_and_waited_for(monkeypatch, tmp_path):
    monkeypatch.setattr("symbiont.service.nightly_tools.POLL_S", 0.0)
    started = []

    def spawn(start, log):
        started.append((start, log))
        return FakeChild()

    said = ensured_judge(START, URL, tmp_path / "log", judge_that_comes_up_after(2), spawn)
    assert started == [(START, tmp_path / "log")]
    assert said.startswith(f"started the judge server at {URL}")


def test_a_judge_that_cannot_start_is_loud_and_gives_the_command(tmp_path):
    def spawn(start, log):
        raise JudgeStartError("no such python")

    said = ensured_judge(START, URL, tmp_path / "log", judge_that_comes_up_after(0), spawn)
    assert said.startswith("symbiont checker offline: no such python")
    assert "LCAP_DEVICE=mps py " in said and "--port 8861" in said


def test_a_judge_process_that_exited_is_reported_at_once_with_its_log(tmp_path):
    with pytest.raises(JudgeStartError, match=r"exited with 3; see .*log"):
        waited_for_judge(URL, FakeChild(3), tmp_path / "log", judge_that_comes_up_after(99))


def test_a_judge_that_never_answers_times_out_naming_the_log(monkeypatch, tmp_path):
    monkeypatch.setattr("symbiont.service.nightly_tools.POLL_S", 0.0)
    with pytest.raises(JudgeStartError, match="did not answer within 0s"):
        waited_for_judge(
            URL, FakeChild(), tmp_path / "log", judge_that_comes_up_after(10**6), timeout_s=0.0
        )


def test_a_missing_judge_script_or_python_raises_judge_start_error(monkeypatch, tmp_path):
    with pytest.raises(JudgeStartError):
        spawn_judge(JudgeStart("/no/such/python", "/b", "/a", None, 8861), tmp_path / "log")
    monkeypatch.setenv("SYMBIONT_ROUTEA_DIR", str(tmp_path))
    with pytest.raises(JudgeStartError, match="script is not here"):
        spawn_judge(START, tmp_path / "log")


def test_start_facts_round_trip_through_the_record_and_bad_ones_read_as_none():
    assert judge_start_from_json(START.as_json()) == START
    assert judge_start_from_json({"python": "py"}) is None
    assert judge_start_from_json(None) is None


def test_the_judge_is_started_on_the_given_python_with_its_arguments_and_device(
    monkeypatch, tmp_path
):
    script = tmp_path / "plug_judge_server.py"
    script.write_text(
        "import os, sys\nprint(os.environ.get('LCAP_DEVICE'), *sys.argv[1:])\n", encoding="utf-8"
    )
    monkeypatch.setenv("SYMBIONT_ROUTEA_DIR", str(tmp_path))
    log = tmp_path / "judge.log"
    child = spawn_judge(JudgeStart(sys.executable, "/base", "/adapter", "mps", 8861), log)
    assert child.wait(timeout=60) == 0
    assert log.read_text(encoding="utf-8").split() == [
        "mps", "--model", "/base", "--adapter", "/adapter", "--port", "8861",
    ]  # fmt: skip

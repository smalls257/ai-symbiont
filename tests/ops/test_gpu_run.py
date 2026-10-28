"""ops/gpu_run.sh against a fake `docker` on PATH.

The fake records every call and keeps `llama`'s Running flag in a file, so the
tests prove the script restores the recorded state on every exit path without
ever touching a real container (the Strix `llama` serves a live job).
"""

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.periphery  # runs a shell script and sleeps

SCRIPT = Path(__file__).resolve().parents[2] / "ops" / "gpu_run.sh"

FAKE_DOCKER = """#!/usr/bin/env bash
echo "$*" >> "$FAKE_DOCKER_CALLS"
state="$FAKE_DOCKER_STATE"
case "$1" in
  inspect) cat "$state" ;;
  stop)    sleep "${FAKE_DOCKER_STOP_SECONDS:-0}"; echo false > "$state" ;;
  start)   # record whether the job was still alive when llama came back
           if [ -n "${FAKE_JOB_PIDFILE:-}" ] && [ -f "$FAKE_JOB_PIDFILE" ]; then
             if kill -0 "$(cat "$FAKE_JOB_PIDFILE")" 2>/dev/null; then verdict=alive
             else verdict=gone; fi
             echo "$verdict" >> "$FAKE_DOCKER_CALLS.job"
           fi
           echo true > "$state" ;;
  *)       echo "unexpected docker call: $*" >&2; exit 99 ;;
esac
"""

# util-linux `flock -n FD` locks the open file description behind an inherited fd, so the lock
# outlives the flock process; fcntl.flock does the same, which makes this a faithful stand-in on
# machines without util-linux (the Strix has the real one).
FAKE_FLOCK = """#!/usr/bin/env python3
import fcntl, sys
args = sys.argv[1:]
mode = fcntl.LOCK_EX | (fcntl.LOCK_NB if "-n" in args else 0)
try:
    fcntl.flock(int(args[-1]), mode)
except BlockingIOError:
    sys.exit(1)
"""


class Rig:
    def __init__(self, tmp_path: Path, running: bool):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "docker").write_text(FAKE_DOCKER)
        (bin_dir / "docker").chmod(0o755)
        (bin_dir / "flock").write_text(FAKE_FLOCK)
        (bin_dir / "flock").chmod(0o755)
        other = tmp_path / "other-project"
        other.mkdir()
        self.foreign = [other / "gpu.lock", other / "gpu.lock.1"]
        self.state = tmp_path / "state"
        self.calls = tmp_path / "calls"
        self.log = tmp_path / "gpu_run.log"
        self.lock = tmp_path / "gpu_run.lock"
        self.calls.touch()
        self.state.write_text("true\n" if running else "false\n")
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE_DOCKER_STATE": str(self.state),
            "FAKE_DOCKER_CALLS": str(self.calls),
            "GPU_RUN_LOG": str(self.log),
            "GPU_RUN_LOCK": str(self.lock),
            "GPU_RUN_GRACE": "1",
            "GPU_RUN_FOREIGN_LOCKS": " ".join(str(path) for path in self.foreign),
            "FAKE_JOB_PIDFILE": str(tmp_path / "job.pid"),
        }
        self.job_pid_file = tmp_path / "job.pid"
        self.job_seen_at_start = Path(str(self.calls) + ".job")

    def run(self, *job: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(SCRIPT), "--", *job],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def start(self, *job: str) -> subprocess.Popen:
        return subprocess.Popen(
            ["bash", str(SCRIPT), "--", *job],
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            # A runner that backgrounds pytest leaves SIGINT ignored, and an
            # ignored-on-entry signal can never be trapped; start from default.
            preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL),
        )

    def running(self) -> bool:
        return self.state.read_text().strip() == "true"

    def docker_calls(self) -> list[str]:
        return self.calls.read_text().splitlines()

    def wait_for(self, path: Path) -> None:
        for _ in range(100):
            if path.exists():
                return
            time.sleep(0.05)
        raise AssertionError(f"{path} never appeared")


@pytest.fixture
def was_running(tmp_path):
    return Rig(tmp_path, running=True)


@pytest.fixture
def was_stopped(tmp_path):
    return Rig(tmp_path, running=False)


def test_running_llama_is_stopped_for_the_job_and_restarted_after(was_running, tmp_path):
    seen = tmp_path / "seen"
    done = was_running.run("bash", "-c", f"cat {was_running.state} > {seen}")
    assert done.returncode == 0
    assert seen.read_text().strip() == "false"  # stopped while the job ran
    assert was_running.running() is True
    assert not was_running.lock.exists()


def test_job_exit_code_is_returned_and_state_still_restored(was_running):
    done = was_running.run("bash", "-c", "exit 7")
    assert done.returncode == 7
    assert was_running.running() is True
    assert not was_running.lock.exists()


def test_stopped_llama_stays_stopped(was_stopped):
    done = was_stopped.run("true")
    assert done.returncode == 0
    assert was_stopped.running() is False
    assert not any(c.startswith(("start", "stop")) for c in was_stopped.docker_calls())


def test_stopped_llama_stays_stopped_when_job_fails(was_stopped):
    assert was_stopped.run("false").returncode == 1
    assert was_stopped.running() is False


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_signal_restores_recorded_state_and_releases_lock(was_running, tmp_path, sig):
    started = tmp_path / "started"
    proc = was_running.start("bash", "-c", f"touch {started}; sleep 30")
    was_running.wait_for(started)
    proc.send_signal(sig)
    proc.communicate(timeout=30)
    assert proc.returncode == 128 + sig
    assert was_running.running() is True
    assert not was_running.lock.exists()


def test_signal_with_stopped_llama_leaves_it_stopped(was_stopped, tmp_path):
    started = tmp_path / "started"
    proc = was_stopped.start("bash", "-c", f"touch {started}; sleep 30")
    was_stopped.wait_for(started)
    proc.send_signal(signal.SIGTERM)
    proc.communicate(timeout=30)
    assert was_stopped.running() is False


def test_second_job_is_refused_and_leaves_the_first_one_alone(was_running, tmp_path):
    started, release = tmp_path / "started", tmp_path / "release"
    wait_for_release = f"touch {started}; while [ ! -e {release} ]; do sleep 0.05; done"
    first = was_running.start("bash", "-c", wait_for_release)
    was_running.wait_for(started)
    second = was_running.run("true")
    assert second.returncode != 0
    assert "held" in second.stderr
    assert was_running.lock.exists()  # the refused job did not release the first's lock
    assert was_running.running() is False  # nor restart llama under it
    release.touch()
    first.communicate(timeout=30)
    assert first.returncode == 0
    assert was_running.running() is True


def test_stale_lock_is_refused_and_names_the_state_to_restore(was_running):
    was_running.lock.mkdir()
    (was_running.lock / "pid").write_text("999999\n")
    (was_running.lock / "llama_was_running").write_text("true\n")
    done = was_running.run("true")
    assert done.returncode != 0
    assert "llama_was_running=true" in done.stderr
    assert was_running.docker_calls() == []


def test_only_llama_is_ever_touched(was_running):
    was_running.run("true")
    calls = was_running.docker_calls()
    assert calls, "expected docker calls"
    assert all(c.split()[-1] == "llama" for c in calls)
    assert {c.split()[0] for c in calls} == {"inspect", "stop", "start"}


def test_unreadable_state_aborts_before_stopping_anything(tmp_path):
    rig = Rig(tmp_path, running=True)
    rig.state.write_text("garbage\n")
    done = rig.run("true")
    assert done.returncode != 0
    assert not any(c.startswith(("stop", "start")) for c in rig.docker_calls())
    assert not rig.lock.exists()


def test_log_records_start_stop_and_exit_code(was_running):
    was_running.run("bash", "-c", "exit 3")
    log = was_running.log.read_text()
    assert "start" in log and "end" in log and "exit=3" in log and "llama_was_running=true" in log


def test_script_never_invokes_sudo():
    code = [ln for ln in SCRIPT.read_text().splitlines() if not ln.lstrip().startswith("#")]
    assert not any("sudo" in ln for ln in code)


# --- signals before the job starts, HUP, and jobs that ignore TERM -------------

STOPPING = {signal.SIGINT: 130, signal.SIGTERM: 143, signal.SIGHUP: 129}
RECORD_PID_THEN_SLEEP = "echo $$ > {pid}; touch {started}; exec sleep 30"


def job_is_gone(rig: Rig) -> bool:
    pid = int(rig.job_pid_file.read_text())
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


@pytest.mark.parametrize("sig", list(STOPPING))
def test_signal_during_docker_stop_aborts_without_starting_the_job(was_running, tmp_path, sig):
    was_running.env["FAKE_DOCKER_STOP_SECONDS"] = "1.5"
    started = tmp_path / "started"
    proc = was_running.start("touch", str(started))
    for _ in range(100):
        if any(c.startswith("stop") for c in was_running.docker_calls()):
            break
        time.sleep(0.02)
    proc.send_signal(sig)
    proc.communicate(timeout=30)
    assert not started.exists()
    assert proc.returncode == STOPPING[sig]
    assert was_running.running() is True
    assert not was_running.lock.exists()


def test_hup_stops_the_job_before_llama_is_restored(was_running, tmp_path):
    started = tmp_path / "started"
    job = RECORD_PID_THEN_SLEEP.format(pid=was_running.job_pid_file, started=started)
    proc = was_running.start("bash", "-c", job)
    was_running.wait_for(started)
    proc.send_signal(signal.SIGHUP)
    proc.communicate(timeout=30)
    assert proc.returncode == 129
    assert job_is_gone(was_running)
    assert was_running.job_seen_at_start.read_text().split() == ["gone"]
    assert was_running.running() is True
    assert not was_running.lock.exists()


def test_job_ignoring_term_is_killed_after_grace_then_llama_restored(was_running, tmp_path):
    started = tmp_path / "started"
    stubborn = (
        f'trap "" TERM HUP INT; echo $$ > {was_running.job_pid_file}; '
        f"touch {started}; while :; do sleep 0.1; done"
    )
    proc = was_running.start("bash", "-c", stubborn)
    was_running.wait_for(started)
    began = time.monotonic()
    proc.send_signal(signal.SIGTERM)
    time.sleep(0.3)
    proc.send_signal(signal.SIGINT)  # a second signal mid-cleanup must not cut the wait short
    time.sleep(0.2)
    proc.send_signal(signal.SIGHUP)
    _, err = proc.communicate(timeout=30)
    assert proc.returncode == 143  # the first signal decides
    assert time.monotonic() - began >= 0.9  # waited out the 1 s grace
    assert job_is_gone(was_running)
    assert was_running.job_seen_at_start.read_text().split() == ["gone"]
    assert "KILL" in err
    assert was_running.running() is True
    assert not was_running.lock.exists()


def hold(path: Path):
    """Take `path` the way the other project's gpu_run does; close the file to release it."""
    import fcntl

    held = path.open("a")
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return held


def is_free(path: Path) -> bool:
    import fcntl

    with path.open("a") as probe:
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True


def test_a_foreign_job_holding_its_lock_makes_us_wait_before_llama_is_stopped(
    was_running, tmp_path
):
    started = tmp_path / "started"
    foreign_job = hold(was_running.foreign[1])  # the other project's second slot
    proc = was_running.start("bash", "-c", f"touch {started}")
    time.sleep(1.5)
    assert not started.exists()
    assert was_running.running() is True  # Glimmer is not stopped while we wait
    foreign_job.close()
    assert proc.wait(timeout=20) == 0
    assert started.exists()
    assert was_running.running() is True
    assert "waiting for foreign lock" in was_running.log.read_text()


def test_while_our_job_runs_every_foreign_slot_is_held(was_running, tmp_path):
    started = tmp_path / "started"
    proc = was_running.start("bash", "-c", f"touch {started}; sleep 3")
    was_running.wait_for(started)
    assert not any(is_free(path) for path in was_running.foreign)
    assert proc.wait(timeout=20) == 0
    assert all(is_free(path) for path in was_running.foreign)


def test_foreign_wait_times_out_with_75_and_touches_nothing(was_running):
    held = hold(was_running.foreign[0])
    was_running.env["GPU_RUN_FOREIGN_WAIT"] = "2"
    done = was_running.run("true")
    held.close()
    assert done.returncode == 75
    assert "still held" in done.stderr
    assert was_running.docker_calls() == []
    assert not was_running.lock.exists()


def test_a_missing_foreign_lock_dir_refuses_rather_than_skipping_it(was_running, tmp_path):
    was_running.env["GPU_RUN_FOREIGN_LOCKS"] = str(tmp_path / "nowhere" / "gpu.lock")
    done = was_running.run("true")
    assert done.returncode == 69
    assert "foreign lock dir missing" in done.stderr
    assert was_running.docker_calls() == []
    assert not was_running.lock.exists()


def test_term_during_the_foreign_wait_ends_it_and_leaves_llama_running(was_running):
    held = hold(was_running.foreign[0])
    proc = was_running.start("true")
    time.sleep(1.5)
    proc.send_signal(signal.SIGTERM)
    assert proc.wait(timeout=10) == 128 + signal.SIGTERM
    held.close()
    assert was_running.running() is True
    assert was_running.docker_calls() == []
    assert not was_running.lock.exists()

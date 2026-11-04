"""`symbiont repo mine` starts the service's job, opens the dashboard on it and follows it.

Failures guarded against: a Black Box (mining that shows nothing), a Silent Fallback (a failed
run, a down service or a missing browser that look like success) and a Distributed Monolith (the
command mining on its own instead of asking the service that owns the store). No test opens a
real browser: the opener is injected.
"""

import pytest

from claude_logs import claude_log, install_claude_session
from live_service import serving
from symbiont import cli
from symbiont.delivery import open_page
from symbiont.delivery.recall import call_service
from symbiont.service.asking import ServiceUnavailableError
from symbiont.store.repos import RepoRegistry, RepoStance

pytestmark = pytest.mark.periphery


class Desk:
    """A repository with one Claude Code session, a service of its own and a fake browser."""

    def __init__(self, tmp_path, monkeypatch, project="demo"):
        self.repo, self.home, self.data = tmp_path / "repo", tmp_path / "home", tmp_path / "data"
        self.project = project
        self.repo.mkdir()
        monkeypatch.setenv("HOME", str(self.home))
        monkeypatch.setenv("USERPROFILE", str(self.home))  # Path.home() on Windows
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        install_claude_session(self.home, self.repo, claude_log())
        RepoRegistry(self.data).record_stance(project, RepoStance.GIVEN)
        self.opened: list[str] = []
        self.calls: list[str] = []

    def mine(self, *extra, port, log_text=None, ask=None):
        if log_text is not None:
            install_claude_session(self.home, self.repo, log_text)
        argv = ["repo", "mine", "--project", self.project, "--data-dir", str(self.data)]
        argv += ["--repo-dir", str(self.repo), "--port", str(port), *extra]
        return cli.main(argv, open_page=self._open, mine_ask=ask)

    def _open(self, url):
        self.opened.append(url)
        return True


@pytest.fixture
def desk(tmp_path, monkeypatch):
    return Desk(tmp_path, monkeypatch)


def test_mining_opens_the_dashboard_on_the_started_job_and_prints_the_address(desk, capsys):
    with serving(desk.data) as (_, port):
        assert desk.mine(port=port) == 0

    out = capsys.readouterr().out
    url = f"http://127.0.0.1:{port}/dashboard?project=demo&mining=1"
    assert desk.opened == [url]
    assert f"dashboard: {url}" in out
    assert "reading sessions" in out or "learned 1 lessons" in out
    assert "learned 1 lessons from 1 claude-code sessions, 0 muse-code sessions" in out


def test_the_job_is_started_in_the_service_before_the_browser_opens(desk):
    order = []

    def ask(route, body, port):
        order.append(route)
        return call_service(route, body, port)

    desk.opened = order
    with serving(desk.data) as (_, port):
        assert desk.mine(port=port, ask=ask) == 0

    assert order[0] == "/mine" and order[1].startswith("http://127.0.0.1")


def test_no_open_prints_the_address_and_opens_nothing(desk, capsys):
    with serving(desk.data) as (_, port):
        assert desk.mine("--no-open", port=port) == 0

    assert desk.opened == []
    assert (
        f"dashboard: http://127.0.0.1:{port}/dashboard?project=demo&mining=1"
        in capsys.readouterr().out
    )


def test_the_setting_turns_opening_off_and_keeps_the_other_settings(desk, capsys):
    data = ["--project", "demo", "--data-dir", str(desk.data)]
    cli.main(["settings", "set", "cross_harness", "true", *data])
    cli.main(["settings", "set", "open_dashboard_on_mine", "false", *data])
    shown = capsys.readouterr().out
    assert "open_dashboard_on_mine=False" in shown and "cross_harness=True" in shown

    with serving(desk.data) as (_, port):
        assert desk.mine(port=port) == 0

    assert desk.opened == []
    assert "dashboard: http://127.0.0.1" in capsys.readouterr().out


def test_a_machine_that_cannot_open_a_browser_is_told_so(desk, capsys):
    with serving(desk.data) as (_, port):
        argv = ["repo", "mine", "--project", "demo", "--data-dir", str(desk.data)]
        argv += ["--repo-dir", str(desk.repo), "--port", str(port)]
        assert cli.main(argv, open_page=lambda url: False) == 0

    out = capsys.readouterr().out
    assert "could not open a browser here; open the address above" in out
    assert "dashboard: http://127.0.0.1" in out


def test_a_down_service_is_offline_not_a_quiet_success(desk, capsys):
    def down(route, body, port):
        raise ServiceUnavailableError("could not reach the local service")

    assert desk.mine(port=1, ask=down) == 1

    assert "symbiont offline: could not reach the local service" in capsys.readouterr().out
    assert desk.opened == []


def test_a_job_that_fails_exits_nonzero_with_its_reason(desk, capsys):
    with serving(desk.data) as (_, port):
        code = desk.mine(port=port, log_text="this is not json\n")

    err = capsys.readouterr().err
    assert code == 1 and "mining failed" in err and "one.jsonl" in err


def test_a_project_name_with_spaces_makes_a_valid_address(tmp_path, monkeypatch, capsys):
    desk = Desk(tmp_path, monkeypatch, project="my repo")
    with serving(desk.data) as (_, port):
        assert desk.mine(port=port) == 0

    assert desk.opened == [f"http://127.0.0.1:{port}/dashboard?project=my%20repo&mining=1"]


def test_a_repository_nobody_allowed_is_refused_before_anything_opens(desk, capsys):
    RepoRegistry(desk.data).forget_project("demo")
    with serving(desk.data) as (_, port):
        assert desk.mine(port=port) == 1

    assert "repo allow" in capsys.readouterr().err
    assert desk.opened == []


def test_the_opener_picks_the_desktop_command_and_reports_a_missing_one(monkeypatch):
    started = []
    monkeypatch.setattr(open_page.subprocess, "Popen", lambda command, **_: started.append(command))

    monkeypatch.setattr(open_page.sys, "platform", "darwin")
    assert open_page.open_in_browser("http://x") is True
    monkeypatch.setattr(open_page.sys, "platform", "linux")
    assert open_page.open_in_browser("http://x") is True
    assert started == [["open", "http://x"], ["xdg-open", "http://x"]]

    monkeypatch.setattr(open_page.sys, "platform", "freebsd")
    assert open_page.open_in_browser("http://x") is False

    def missing(*args, **kwargs):
        raise FileNotFoundError("xdg-open")

    monkeypatch.setattr(open_page.sys, "platform", "linux")
    monkeypatch.setattr(open_page.subprocess, "Popen", missing)
    assert open_page.open_in_browser("http://x") is False


def test_windows_opens_the_page_with_explorer_detached_by_creation_flags(monkeypatch):
    seen = []
    monkeypatch.setattr(open_page.subprocess, "Popen", lambda c, **o: seen.append((c, o)))
    monkeypatch.setattr(open_page.sys, "platform", "win32")

    assert open_page.open_in_browser("http://127.0.0.1:1/dashboard?project=a%20b") is True

    command, options = seen[0]
    assert command == ["explorer", "http://127.0.0.1:1/dashboard?project=a%20b"]
    assert options["creationflags"] == 0x08 | 0x200 | 0x01000000
    assert "start_new_session" not in options

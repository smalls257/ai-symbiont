"""`symbiont dashboard [view] [--open]`: every view has its address; offline never gives a link."""

from urllib.request import urlopen

import pytest
from tests.live_service import serving

from symbiont import cli
from symbiont.records.dashboard_views import DashboardView, dashboard_address

pytestmark = pytest.mark.periphery


def run(tmp_path, *words, opened=None, port):
    def open_page(url):
        if opened is not None:
            opened.append(url)
        return True

    argv = ["dashboard", *words, "--project", "demo", "--data-dir", str(tmp_path)]
    return cli.main([*argv, "--port", str(port)], open_page=open_page)


def test_no_view_means_the_inbox(tmp_path, capsys):
    with serving(tmp_path) as (_, port):
        assert run(tmp_path, port=port) == 0
    assert capsys.readouterr().out.strip() == (
        f"http://127.0.0.1:{port}/dashboard?project=demo&view=inbox"
    )


@pytest.mark.parametrize("view", list(DashboardView))
def test_each_view_prints_its_own_address(tmp_path, capsys, view):
    with serving(tmp_path) as (_, port):
        assert run(tmp_path, view.value, port=port) == 0
    shown = capsys.readouterr().out.strip()
    assert shown.endswith(f"&view={view.value}")
    assert shown == dashboard_address(port, "demo", view)


def test_an_unknown_view_is_refused_listing_the_views(tmp_path, capsys):
    with pytest.raises(SystemExit):
        run(tmp_path, "nope", port=1)
    err = capsys.readouterr().err
    assert all(view.value in err for view in DashboardView)


def test_open_opens_the_address_once(tmp_path, capsys):
    opened: list[str] = []
    with serving(tmp_path) as (_, port):
        assert run(tmp_path, "topics", "--open", opened=opened, port=port) == 0
    assert opened == [f"http://127.0.0.1:{port}/dashboard?project=demo&view=topics"]


def test_without_open_nothing_is_opened(tmp_path):
    opened: list[str] = []
    with serving(tmp_path) as (_, port):
        run(tmp_path, "topics", opened=opened, port=port)
    assert opened == []


def test_a_down_service_prints_offline_and_opens_nothing(tmp_path, capsys):
    opened: list[str] = []
    assert run(tmp_path, "topics", "--open", opened=opened, port=1) == 0
    out = capsys.readouterr().out
    assert out.startswith("symbiont offline")
    assert "/dashboard" not in out
    assert opened == []


def test_the_page_still_loads_with_a_view_it_does_not_read_yet(tmp_path):
    with serving(tmp_path) as (_, port):
        url = dashboard_address(port, "demo", DashboardView.TOPICS)
        with urlopen(url) as reply:
            assert reply.status == 200

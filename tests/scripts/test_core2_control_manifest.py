"""Core D2 control manifest: other repositories only, earliest by date."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROUTEB = Path(__file__).resolve().parents[2] / "scripts" / "routeb"


@pytest.fixture
def mod(monkeypatch):
    monkeypatch.syspath_prepend(str(ROUTEB))
    path = ROUTEB / "core2_control_manifest.py"
    spec = importlib.util.spec_from_file_location("core2_control_manifest", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    for name in ("core_collect_manifest", "core2_train_manifest"):
        sys.modules.pop(name, None)


def test_the_six_d2_repositories_never_enter_the_control_set(mod):
    passes = [{"task": "django__django-1"}, {"task": "x__y-2"}, {"task": "tobymao__sqlglot-3"}]
    kept, inside = mod.other_repos_only(passes)
    assert [r["task"] for r in kept] == ["x__y-2"] and inside == 2


def test_the_earliest_passes_by_date_make_the_set(mod):
    passes = [{"task": f"r__r{n}-1"} for n in (3, 1, 2)]
    dates = {"r__r1-1": "2021", "r__r2-1": "2019", "r__r3-1": "2020"}
    assert [r["task"] for r in mod.earliest(passes, dates, 2)] == ["r__r2-1", "r__r3-1"]
    assert len(mod.earliest(passes, dates, 10)) == 3

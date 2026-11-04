"""The nightly's scripts travel inside the installed package and are found without a checkout.

Violation prevented: Distributed Monolith. The nightly worked only beside a repository checkout;
a `uv tool install` has none, so the scripts ship as package data and unpack on demand.
"""

import py_compile
from pathlib import Path

import pytest

from symbiont.service import nightly_bundle
from symbiont.service.nightly_bundle import (
    BUNDLE,
    BundleMissingError,
    bundled_names,
    judge_script,
    materialized,
    routea_dir,
    torch_trainer,
)
from symbiont.service.nightly_run import NightFailedError

pytestmark = pytest.mark.periphery
SOURCES = Path(__file__).resolve().parents[2] / "scripts" / "routea"
NEEDED = {
    "train_lora_torch",
    "plug_judge_server",
    "merge_adapter_torch",
    "device_choice",
    "mlx_lora_recipe",
    "score_pairs_torch",
    "answer_questions_torch",
}


def test_the_package_carries_every_script_the_nightly_runs():
    assert set(bundled_names()) == NEEDED


@pytest.mark.parametrize("name", sorted(NEEDED))
def test_a_bundled_script_is_the_same_text_as_its_source_in_scripts_routea(name):
    shipped = (BUNDLE / f"{name}.script").read_bytes()
    assert shipped == (SOURCES / f"{name}.py").read_bytes(), (
        f"scripts/routea/{name}.py changed; run: cp scripts/routea/{name}.py "
        f"src/symbiont/service/routea_bundle/{name}.script"
    )


def test_unpacking_writes_py_files_that_compile_and_rewrites_only_what_changed(tmp_path):
    folder = materialized(tmp_path / "unpacked")
    assert {path.stem for path in folder.glob("*.py")} == NEEDED
    for path in folder.glob("*.py"):
        py_compile.compile(str(path), cfile=str(tmp_path / "x.pyc"), doraise=True)
    edited = folder / "device_choice.py"
    edited.write_text("# edited", encoding="utf-8")
    kept = folder / "mlx_lora_recipe.py"
    before = kept.stat().st_mtime_ns
    materialized(folder)
    assert edited.read_bytes() == (BUNDLE / "device_choice.script").read_bytes()
    assert kept.stat().st_mtime_ns == before


def test_the_override_wins_and_a_bad_override_is_named(monkeypatch, tmp_path):
    monkeypatch.setenv("SYMBIONT_ROUTEA_DIR", str(tmp_path))
    assert routea_dir() == tmp_path
    monkeypatch.setenv("SYMBIONT_ROUTEA_DIR", str(tmp_path / "gone"))
    with pytest.raises(NightFailedError, match="SYMBIONT_ROUTEA_DIR"):
        routea_dir()


def test_a_checkout_is_used_when_there_is_one(monkeypatch):
    monkeypatch.delenv("SYMBIONT_ROUTEA_DIR", raising=False)
    assert routea_dir() == nightly_bundle.CHECKOUT_ROUTEA


def test_an_install_without_a_checkout_unpacks_the_package_under_home(monkeypatch, tmp_path):
    monkeypatch.delenv("SYMBIONT_ROUTEA_DIR", raising=False)
    monkeypatch.setattr(nightly_bundle, "CHECKOUT_ROUTEA", tmp_path / "no-checkout")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert routea_dir() == tmp_path / ".symbiont" / "routea"
    assert Path(judge_script()).is_file()
    assert torch_trainer().name == "train_lora_torch.py"


def test_a_package_with_no_scripts_says_to_reinstall(monkeypatch, tmp_path):
    monkeypatch.setattr(nightly_bundle, "BUNDLE", tmp_path)
    with pytest.raises(BundleMissingError, match="reinstall"):
        bundled_names()
    assert "unavailable" in judge_script_when_broken(monkeypatch, tmp_path)


def judge_script_when_broken(monkeypatch, tmp_path):
    monkeypatch.delenv("SYMBIONT_ROUTEA_DIR", raising=False)
    monkeypatch.setattr(nightly_bundle, "CHECKOUT_ROUTEA", tmp_path / "no-checkout")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return judge_script()

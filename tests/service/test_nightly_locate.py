"""Finding the base and the kit by themselves; every root is a tmp dir, never the real home."""

import os
from pathlib import Path

import pytest

from symbiont.service.nightly_background import KitFiles
from symbiont.service.nightly_locate import (
    HF_BASE_CACHE,
    HF_KIT_CACHE,
    ModelsNotFoundError,
    SearchRoots,
    locate_base,
    locate_kit_files,
    resolved_downloads,
    search_roots,
)
from symbiont.service.nightly_setup import KIT_PINS, KIT_PLAIN_FILES, KIT_REPO


def roots(tmp_path) -> SearchRoots:
    return SearchRoots(tmp_path / "home" / ".symbiont" / "models", tmp_path / "hub")


def make_base(folder: Path, weights: bool = True) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.json").write_text("{}")
    if weights:
        (folder / "model.safetensors").write_bytes(b"w")
    return folder


def make_kit(folder: Path, skip: str | None = None) -> Path:
    for name in (*KIT_PINS, *KIT_PLAIN_FILES):
        if name != skip:
            (folder / name).parent.mkdir(parents=True, exist_ok=True)
            (folder / name).write_bytes(b"k")
    return folder


def snapshot(hub: Path, cache: str, name: str, age: int) -> Path:
    folder = hub / cache / "snapshots" / name
    folder.mkdir(parents=True)
    os.utime(folder, (age, age))
    return folder


def test_search_roots_use_hf_home_hub_when_set_else_the_default_cache(tmp_path):
    set_ = search_roots({"HF_HOME": str(tmp_path / "hf")}, tmp_path / ".symbiont", tmp_path)
    assert set_.hf_hub == tmp_path / "hf" / "hub"
    unset = search_roots({}, tmp_path / ".symbiont", tmp_path)
    assert unset.hf_hub == tmp_path / ".cache" / "huggingface" / "hub"
    assert unset.models == tmp_path / ".symbiont" / "models"


def test_base_in_symbionts_own_folder_is_found(tmp_path):
    own = make_base(roots(tmp_path).models / "llama-3.2-1b-instruct")
    assert locate_base(roots(tmp_path)) == own


def test_base_in_the_hub_cache_is_found_and_the_newest_snapshot_wins(tmp_path):
    hub = roots(tmp_path).hf_hub
    make_base(snapshot(hub, HF_BASE_CACHE, "old", 100))
    new = make_base(snapshot(hub, HF_BASE_CACHE, "new", 200))
    assert locate_base(roots(tmp_path)) == new


def test_own_folder_beats_the_hub_cache(tmp_path):
    make_base(snapshot(roots(tmp_path).hf_hub, HF_BASE_CACHE, "s", 100))
    own = make_base(roots(tmp_path).models / "llama-3.2-1b-instruct")
    assert locate_base(roots(tmp_path)) == own


def test_a_newest_snapshot_without_weights_is_skipped_for_an_older_valid_one(tmp_path):
    hub = roots(tmp_path).hf_hub
    good = make_base(snapshot(hub, HF_BASE_CACHE, "good", 100))
    make_base(snapshot(hub, HF_BASE_CACHE, "partial", 200), weights=False)
    assert locate_base(roots(tmp_path)) == good


def test_nothing_found_is_none(tmp_path):
    assert locate_base(roots(tmp_path)) is None
    assert locate_kit_files(roots(tmp_path)) is None


def test_kit_in_own_folder_and_in_the_hub_snapshot(tmp_path):
    inside = make_kit(snapshot(roots(tmp_path).hf_hub, HF_KIT_CACHE, "s", 100) / "nightly-kit")
    assert locate_kit_files(roots(tmp_path)) == inside
    own = make_kit(roots(tmp_path).models / "nightly-kit")
    assert locate_kit_files(roots(tmp_path)) == own


def test_a_kit_folder_missing_a_file_is_rejected(tmp_path):
    make_kit(roots(tmp_path).models / "nightly-kit", skip="habits.jsonl")
    assert locate_kit_files(roots(tmp_path)) is None


def test_explicit_folders_win_over_anything_found(tmp_path):
    make_base(roots(tmp_path).models / "llama-3.2-1b-instruct")
    given = KitFiles(tmp_path / "mine-base", tmp_path / "mine-kit")
    assert resolved_downloads(given, tmp_path / "judge-kit", roots(tmp_path)) == given


def test_one_given_folder_is_kept_and_the_other_is_found(tmp_path):
    kit = make_kit(roots(tmp_path).models / "nightly-kit")
    given = KitFiles(tmp_path / "mine-base", None)
    found = resolved_downloads(given, tmp_path / "judge-kit", roots(tmp_path))
    assert found == KitFiles(tmp_path / "mine-base", kit)


def test_found_folders_are_returned_together(tmp_path):
    base = make_base(roots(tmp_path).models / "llama-3.2-1b-instruct")
    kit = make_kit(roots(tmp_path).models / "nightly-kit")
    found = resolved_downloads(KitFiles(None, None), tmp_path / "judge-kit", roots(tmp_path))
    assert found == KitFiles(base, kit)


def test_a_missing_model_says_what_is_missing_where_it_looked_and_the_exact_downloads(tmp_path):
    make_kit(roots(tmp_path).models / "nightly-kit")
    with pytest.raises(ModelsNotFoundError) as raised:
        resolved_downloads(KitFiles(None, None), tmp_path / "judge-kit", roots(tmp_path))
    text = str(raised.value)
    assert text.startswith("no Llama 3.2 1B Instruct model found")
    assert str(roots(tmp_path).hf_hub) in text
    for piece in (
        "https://huggingface.co/meta-llama/Llama-3.2-1B-Instruct",
        "`hf auth login`",
        "`hf download meta-llama/Llama-3.2-1B-Instruct`",
        f'`hf download {KIT_REPO} --include "nightly-kit/*"`',
        "run /symbiont onboard again",
    ):
        assert piece in text


def test_a_complete_judge_kit_needs_no_search(tmp_path):
    from nightly_support import write_kit

    write_kit(tmp_path / "judge-kit")
    given = KitFiles(None, None)
    assert resolved_downloads(given, tmp_path / "judge-kit", roots(tmp_path)) == given

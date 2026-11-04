"""Which files the first night downloads and where; the network is a fake lister and fetcher."""

import pytest

from symbiont.egress import DownloadError, listing_url
from symbiont.service.nightly_fetch import (
    BASE_FILES,
    BASE_REPO,
    download_models,
    files_to_fetch,
    plan_downloads,
    still_missing,
)
from symbiont.service.nightly_setup import KIT_REPO

BASE_LISTING = [
    {"type": "file", "path": name, "size": 10 + index}
    for index, name in enumerate(sorted(BASE_FILES))
] + [
    {"type": "file", "path": ".gitattributes", "size": 5},
    {"type": "file", "path": "README.md", "size": 5},
]
KIT_LISTING = [
    {"type": "directory", "path": "nightly-kit/general", "size": 0},
    {"type": "file", "path": "nightly-kit/habits.jsonl", "size": 7},
    {"type": "file", "path": "nightly-kit/general/adapter_config.json", "size": 9},
]


def lister(url):
    return BASE_LISTING if BASE_REPO in url else KIT_LISTING


def test_listing_urls_go_to_the_api_of_the_right_repo():
    assert (
        listing_url(BASE_REPO)
        == f"https://huggingface.co/api/models/{BASE_REPO}/tree/main?recursive=1"
    )
    assert listing_url(KIT_REPO, "nightly-kit").endswith("/tree/main/nightly-kit?recursive=1")


def test_only_the_wanted_base_files_are_planned_and_subfolders_keep_their_path(tmp_path):
    plan = plan_downloads(tmp_path, lister)
    names = {f.target.relative_to(tmp_path).as_posix() for f in plan}
    assert {f"llama-3.2-1b-instruct/{name}" for name in BASE_FILES} <= names
    assert "llama-3.2-1b-instruct/README.md" not in names
    assert (
        "nightly-kit/general/adapter_config.json" in names and "nightly-kit/habits.jsonl" in names
    )
    assert all(f.url.startswith("https://huggingface.co/") for f in plan)


def test_directories_are_not_files(tmp_path):
    found = files_to_fetch(KIT_LISTING, KIT_REPO, "nightly-kit/", None, tmp_path)
    assert len(found) == 2


def test_a_repo_that_lost_a_base_file_is_a_named_error(tmp_path):
    thin = [e for e in BASE_LISTING if e["path"] != "model.safetensors"]
    with pytest.raises(DownloadError, match="model.safetensors"):
        plan_downloads(tmp_path, lambda url: thin if BASE_REPO in url else KIT_LISTING)


def test_files_with_the_right_size_are_skipped_and_wrong_sized_ones_are_refetched(tmp_path):
    plan = plan_downloads(tmp_path, lister)
    good, wrong = plan[0], plan[1]
    good.target.parent.mkdir(parents=True, exist_ok=True)
    good.target.write_bytes(b"x" * good.size)
    wrong.target.write_bytes(b"x" * (wrong.size + 1))
    left = still_missing(plan)
    assert good not in left and wrong in left and len(left) == len(plan) - 1


def test_download_models_fetches_only_what_is_missing_and_reports_growing_totals(tmp_path):
    fetched, reports = [], []

    def fetch(url, target, size, progress):
        fetched.append(target.name)
        progress(size, size)
        return size

    first = plan_downloads(tmp_path, lister)[0]
    first.target.parent.mkdir(parents=True)
    first.target.write_bytes(b"x" * first.size)
    count = download_models(
        tmp_path, lambda done, total: reports.append((done, total)), lister, fetch
    )
    assert count == len(fetched) == len(plan_downloads(tmp_path, lister)) - 1
    assert first.target.name not in fetched
    assert reports[0][0] == 0 and reports[-1][0] == reports[-1][1] > 0
    assert [done for done, _ in reports] == sorted(done for done, _ in reports)

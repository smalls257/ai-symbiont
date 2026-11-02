"""The reproduction kit: the numbers check, the demo, and the tier 3 bands.

Failures guarded against: a Paper Tiger (a checker that prints PASS whatever the files hold, a
demo that prints a canned note) and a Silent Fallback (a pin mismatch or a missing prerequisite
that reads as success).
"""

import json
import sys
from pathlib import Path

import pytest

REPRODUCE = Path(__file__).resolve().parents[2] / "scripts" / "reproduce"
MODULES = (
    "exact_bounds",
    "check_numbers",
    "see_it_work",
    "rerun_learning",
    "fetch_swe_smith",
    "rescore",
    "stage_adapters",
)


@pytest.fixture(autouse=True)
def kit(monkeypatch):
    monkeypatch.syspath_prepend(str(REPRODUCE))
    yield
    for name in MODULES:
        sys.modules.pop(name, None)


def test_the_exact_bound_matches_values_printed_in_the_committed_results():
    from exact_bounds import clopper_pearson_upper

    assert round(clopper_pearson_upper(0, 501), 4) == 0.0073
    assert round(clopper_pearson_upper(5, 924), 4) == 0.0126
    assert round(clopper_pearson_upper(15, 501), 4) == 0.0489


def test_a_count_larger_than_its_trials_is_refused():
    from exact_bounds import clopper_pearson_upper

    with pytest.raises(ValueError, match="not a count"):
        clopper_pearson_upper(6, 5)


def test_every_headline_claim_recomputes_from_the_committed_files(capsys):
    import check_numbers

    assert check_numbers.main() == 0
    shown = capsys.readouterr().out
    assert "0 MISMATCH" in shown
    assert "Code-fix gain interval, low end" in shown, "the code-fix interval is recomputed"


def test_a_claim_the_files_contradict_is_a_mismatch():
    from check_numbers import Status, recomputed, stored

    assert recomputed("x", 0.611, 0.55, "0.55").status is Status.MISMATCH
    assert stored("x", 0.611, 0.55, "why").status is Status.MISMATCH
    assert recomputed("x", 0.611, 0.6113, "0.6113").status is Status.PASS


def test_a_tampered_cluster_table_changes_the_recomputed_interval(monkeypatch):
    import check_numbers

    real = check_numbers.load

    def tampered(name):
        body = real(name)
        if name == "repro-cluster-tables.json":
            nightly = body["code-fix"]["arms"]["nightly"]
            for counts in nightly.values():
                counts[1] = 0
        return body

    monkeypatch.setattr(check_numbers, "load", tampered)
    lines = check_numbers.code_fix_study()
    assert any(line.status is check_numbers.Status.MISMATCH for line in lines)


def test_the_committed_decision_is_inside_its_own_bands(capsys):
    import rerun_learning

    path = Path(__file__).resolve().parents[2] / "results" / "plug-r4-smith-decision.json"
    assert rerun_learning.compare_stage(path) == 0
    assert "OUT OF BAND" not in capsys.readouterr().out


def test_a_rerun_with_too_many_wrong_picks_is_out_of_band(tmp_path, capsys):
    import rerun_learning

    path = Path(__file__).resolve().parents[2] / "results" / "plug-r4-smith-decision.json"
    decision = json.loads(path.read_text())
    decision["nightly_vs_agree"]["rule"]["wrong_pick"] = 40 / 924
    worse = tmp_path / "decision.json"
    worse.write_text(json.dumps(decision))

    assert rerun_learning.compare_stage(worse) == 1
    assert "OUT OF BAND  wrong picks" in capsys.readouterr().out


def test_a_missing_prerequisite_exits_three_and_says_what_is_missing(tmp_path, capsys):
    import rerun_learning

    code = rerun_learning.prerequisites_stage(tmp_path, tmp_path)

    assert code == rerun_learning.EXIT_MISSING_PREREQUISITE
    assert "NOT RUN" in capsys.readouterr().err


def test_the_raw_pins_name_both_repositories_and_the_revision():
    pins = json.loads((REPRODUCE.parents[1] / "results" / "repro-swe-smith-pins.json").read_text())
    assert len(pins["dataset_revision"]) == 40
    assert set(pins["raw_sha256"]) == {"pydantic__pydantic", "getmoto__moto"}


def test_a_file_that_differs_from_its_pin_stops_the_fetch(tmp_path):
    import fetch_swe_smith

    for repo in fetch_swe_smith.REPOS:
        (tmp_path / f"{repo}.jsonl").write_text("{}\n")

    with pytest.raises(fetch_swe_smith.PinMismatchError, match="the pins say"):
        fetch_swe_smith.verify(tmp_path, fetch_swe_smith.load_pins())


@pytest.mark.periphery
def test_the_example_repository_fails_on_purpose_for_the_rule_it_documents(tmp_path):
    import subprocess

    import see_it_work

    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--tb=short",
            "-rN",
            "-k",
            "invoice",
            "-p",
            "no:cacheprovider",
        ],
        cwd=see_it_work.EXAMPLE,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 1
    assert "AssertionError: ledger/invoices.py" in done.stdout
    assert "minor units" in (see_it_work.EXAMPLE / "docs" / "currencies.md").read_text()


@pytest.mark.periphery
def test_the_demo_ends_with_a_note_that_names_the_earlier_fix(capsys):
    import see_it_work

    assert see_it_work.main() == 0
    shown = capsys.readouterr().out
    assert "Last time, `pytest` failed with AssertionError" in shown
    assert "currency_exponent" in shown
    assert "[symbiont] In this repo: Amounts are integers" in shown
    assert "PASS" in shown


def test_a_note_that_does_not_name_the_earlier_fix_fails_the_demo():
    import see_it_work

    with pytest.raises(see_it_work.DemoError, match="invoices.py"):
        see_it_work.check_note_names_the_earlier_fix(
            "Last time, `pytest` failed with AssertionError."
        )


def test_an_adapter_file_that_differs_from_its_pin_is_refused(tmp_path):
    import hashlib

    import rescore

    folder = tmp_path / "judge-s0"
    folder.mkdir()
    (folder / "adapter_model.safetensors").write_bytes(b"weights")
    good = {
        "adapters": {
            "judge-s0": {"adapter_model.safetensors": hashlib.sha256(b"weights").hexdigest()}
        }
    }
    rescore.verify_adapters(tmp_path, good)

    bad = {"adapters": {"judge-s0": {"adapter_model.safetensors": "0" * 64}}}
    with pytest.raises(rescore.AdapterPinError, match="differs from its pin"):
        rescore.verify_adapters(tmp_path, bad)
    with pytest.raises(rescore.AdapterPinError, match="missing judge-s0/adapter_config.json"):
        rescore.verify_adapters(tmp_path, {"adapters": {"judge-s0": {"adapter_config.json": "x"}}})


def test_unpublished_adapters_exit_three_instead_of_passing(monkeypatch, tmp_path, capsys):
    import rerun_learning
    import rescore

    monkeypatch.setattr(rescore, "adapter_pins", lambda: {"repo_id": None, "revision": None})
    monkeypatch.setattr(sys, "argv", ["rerun_learning", "fetch-adapters", "--dest", str(tmp_path)])

    assert rerun_learning.main() == rerun_learning.EXIT_MISSING_PREREQUISITE
    assert "not published yet" in capsys.readouterr().err


def test_a_judge_only_rescore_must_reproduce_the_committed_judge_arms(tmp_path, capsys):
    import rerun_learning

    path = Path(__file__).resolve().parents[2] / "results" / "plug-r4-smith-decision.json"
    committed = json.loads(path.read_text())
    same = tmp_path / "same.json"
    same.write_text(json.dumps({"agree_vs_judge_alone": committed["agree_vs_judge_alone"]}))
    assert rerun_learning.compare_stage(same) == 0

    moved = {"agree_vs_judge_alone": json.loads(json.dumps(committed["agree_vs_judge_alone"]))}
    moved["agree_vs_judge_alone"]["rule"]["answered"] = 3
    other = tmp_path / "moved.json"
    other.write_text(json.dumps(moved))
    assert rerun_learning.compare_stage(other) == 1
    assert "OUT OF BAND  agree rule answers" in capsys.readouterr().out


def test_the_published_pins_name_a_revision_and_only_the_four_published_adapters():
    pins = json.loads((REPRODUCE.parents[1] / "results" / "repro-adapter-pins.json").read_text())
    assert len(pins["revision"]) == 40
    assert set(pins["adapters"]) == {"judge-s0", "judge-s1", "judge-s2", "general"}


def test_the_upload_stage_names_the_base_by_public_id_and_refuses_extra_files(tmp_path):
    import stage_adapters

    source = tmp_path / "adapter_config.json"
    source.write_text(json.dumps({"base_model_name_or_path": "/some/local/path", "r": 16}))
    config = json.loads(stage_adapters.sanitized_config(source))
    assert config["base_model_name_or_path"] == stage_adapters.BASE_ID
    assert config["r"] == 16

    staged = tmp_path / "out"
    (staged / "judge-s0").mkdir(parents=True)
    (staged / "judge-s0" / "tokenizer.json").write_text("{}")
    with pytest.raises(SystemExit, match="refusing to stage"):
        stage_adapters.refuse_extras(staged)


def test_the_adapter_repository_must_be_named_when_the_pins_do_not_keep_it(monkeypatch):
    import rescore

    monkeypatch.delenv("SYMBIONT_ADAPTER_REPO", raising=False)
    with pytest.raises(rescore.AdapterPinError, match="name the model repository"):
        rescore.adapter_repo(None, {"repo_id": None})
    assert rescore.adapter_repo("a/b", {"repo_id": None}) == "a/b"
    monkeypatch.setenv("SYMBIONT_ADAPTER_REPO", "c/d")
    assert rescore.adapter_repo(None, {"repo_id": None}) == "c/d"


def test_the_adapter_repository_may_be_given_as_its_hub_url():
    import rescore

    assert rescore.adapter_repo("https://huggingface.co/a/b", {"repo_id": None}) == "a/b"
    assert rescore.adapter_repo("hf.co/a/b/", {"repo_id": None}) == "a/b"
    named = rescore.repo_id_of(rescore.ADAPTER_REPO_URL)
    assert named.endswith("/Llama-3.2-1B-symbiont-judge-adapters")

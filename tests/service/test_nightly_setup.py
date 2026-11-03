"""Setup checks the downloaded base and kit first, names the fix, never merges a wrong file."""

import json

import pytest

from nightly_support import chat
from symbiont import cli
from symbiont.service import nightly_command
from symbiont.service import nightly_setup as setup
from symbiont.service.nightly_kit import open_kit

pytestmark = pytest.mark.periphery

LLAMA = {"model_type": "llama", "hidden_size": 2048, "num_hidden_layers": 16, "vocab_size": 128256}


def make_base(root, config=LLAMA, template=True, weights=True, tokenizer=True):
    root.mkdir(parents=True)
    (root / "config.json").write_text(json.dumps(config))
    (root / "tokenizer_config.json").write_text("{}")
    if tokenizer:
        (root / "tokenizer.json").write_text("{}")
    if weights:
        (root / "model.safetensors").write_bytes(b"w")
    if template:
        (root / "chat_template.jinja").write_text("t")
    return root


def make_files(root, pins):
    """A kit folder whose files hash to `pins`' replacement values."""
    row = json.dumps(chat("s", "u", "a")) + "\n"
    for name in setup.KIT_PINS:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(row if name.endswith(".jsonl") else name)
    for name in setup.KIT_PLAIN_FILES:
        (root / name).write_text("{}")
    return {name: setup.sha256_of(root / name) for name in setup.KIT_PINS}


def test_a_llama_instruct_folder_passes(tmp_path):
    setup.check_base(make_base(tmp_path / "b"))


@pytest.mark.parametrize(
    ("change", "says"),
    [
        ({"template": False}, "plain base model"),
        ({"weights": False}, "model.safetensors"),
        ({"tokenizer": False}, "tokenizer.json"),
        ({"config": {**LLAMA, "num_hidden_layers": 28}}, "not Llama 3.2 1B"),
    ],
)
def test_a_wrong_base_says_what_to_download(tmp_path, change, says):
    with pytest.raises(setup.KitSetupError, match=says) as raised:
        setup.check_base(make_base(tmp_path / "b", **change))
    assert "huggingface-cli download meta-llama/Llama-3.2-1B-Instruct" in str(raised.value)


def test_a_missing_base_folder_is_named(tmp_path):
    with pytest.raises(setup.KitSetupError, match="config.json"):
        setup.check_base(tmp_path / "nowhere")


def test_kit_files_that_match_their_pins_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "KIT_PINS", make_files(tmp_path, setup.KIT_PINS))
    setup.check_kit_files(tmp_path)


def test_a_changed_kit_file_fails_its_pin(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "KIT_PINS", make_files(tmp_path, setup.KIT_PINS))
    (tmp_path / "general/adapter_model.safetensors").write_text("tampered")
    with pytest.raises(setup.KitSetupError, match="does not match the published kit"):
        setup.check_kit_files(tmp_path)


def test_a_missing_kit_file_is_named(tmp_path):
    with pytest.raises(setup.KitSetupError, match="judge-s0/adapter_model.safetensors"):
        setup.check_kit_files(tmp_path)


def test_the_merge_stacks_judge_s0_then_general_and_installs_a_complete_kit(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "KIT_PINS", make_files(tmp_path / "files", setup.KIT_PINS))
    base, kit = make_base(tmp_path / "base"), tmp_path / "kit"
    calls = []

    def fake_merge(python, args, log, extra):
        model, adapter, out = (
            args[args.index(flag) + 1] for flag in ("--model", "--adapter", "--out")
        )
        calls.append((model, adapter))
        (tmp_path / out).mkdir(parents=True)
        (tmp_path / out / "config.json").write_text("{}")
        return 0

    inputs = setup.SetupInputs(base, tmp_path / "files", kit, "python3")
    kit.mkdir()
    setup.merge_kit(inputs, fake_merge, tmp_path / "merge.py", lambda line: None)
    assert [c[1].rsplit("/", 1)[-1] for c in calls] == ["judge-s0", "general"]
    assert calls[0][0] == str(base)
    assert calls[1][0] == calls[0][0].replace(str(base), str(kit / ".setup-work/merged-0"))
    assert open_kit(kit).base == kit / "base"
    assert not (kit / ".setup-work").exists()


def test_a_failed_merge_raises_and_leaves_no_base(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "KIT_PINS", make_files(tmp_path / "files", setup.KIT_PINS))
    kit = tmp_path / "kit"
    inputs = setup.SetupInputs(make_base(tmp_path / "base"), tmp_path / "files", kit, "python3")
    with pytest.raises(setup.KitSetupError, match="merging judge-s0 failed"):
        setup.merge_kit(inputs, lambda *_: 1, tmp_path / "merge.py", lambda line: None)
    assert not (kit / "base").exists()


def test_a_python_without_torch_is_named(tmp_path):
    with pytest.raises(setup.KitSetupError, match="--judge-python"):
        setup.check_merge_python("python3", lambda *_: 1, tmp_path / "log")


def test_the_command_fails_loudly_with_the_download_line_for_a_bad_base(tmp_path):
    argv = ["nightly", "setup", "--base", str(tmp_path / "no"), "--kit-files", str(tmp_path)]
    argv += ["--kit", str(tmp_path / "kit"), "--data-dir", str(tmp_path / "data")]
    said = []
    code = nightly_command.run_nightly_command(cli._parser().parse_args(argv), said.append)
    assert code == 1
    assert "FAILED" in said[-1]
    assert "huggingface-cli download meta-llama/Llama-3.2-1B-Instruct" in said[-1]


def test_the_command_does_nothing_when_the_kit_is_already_complete(tmp_path):
    kit = tmp_path / "kit"
    (kit / "base").mkdir(parents=True)
    (kit / "base" / "config.json").write_text("{}")
    for name in (setup.GENERAL_ROWS, setup.HABITS):
        (kit / name).write_text(json.dumps(chat("s", "u", "a")) + "\n")
    argv = ["nightly", "setup", "--base", "x", "--kit-files", "y", "--kit", str(tmp_path / "kit")]
    said = []
    code = nightly_command.run_nightly_command(cli._parser().parse_args(argv), said.append)
    assert code == 0
    assert "already complete" in said[-1]


def setup_argv(tmp_path, kit):
    return [
        "nightly", "setup", "--base", str(tmp_path / "base"),
        "--kit-files", str(tmp_path / "files"), "--kit", str(kit),
        "--data-dir", str(tmp_path / "data"),
    ]  # fmt: skip


def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "KIT_PINS", make_files(tmp_path / "files", setup.KIT_PINS))
    make_base(tmp_path / "base")
    routea = tmp_path / "routea"
    routea.mkdir()
    (routea / "merge_adapter_torch.py").write_text("")
    monkeypatch.setenv("SYMBIONT_ROUTEA_DIR", str(routea))
    return tmp_path / "kit"


def run_setup(tmp_path, kit, runner, monkeypatch):
    monkeypatch.setattr(nightly_command, "run_logged", runner)
    said = []
    args = cli._parser().parse_args(setup_argv(tmp_path, kit))
    return nightly_command.run_nightly_command(args, said.append), said


def test_the_command_builds_a_complete_kit(tmp_path, monkeypatch):
    kit = prepared(tmp_path, monkeypatch)

    def runner(python, args, log, extra):
        if args[0] == "-c":
            return 0
        out = tmp_path / args[args.index("--out") + 1]
        out.mkdir(parents=True)
        (out / "config.json").write_text("{}")
        return 0

    code, said = run_setup(tmp_path, kit, runner, monkeypatch)
    assert code == 0, said
    assert open_kit(kit).base == kit / "base"
    assert "ready" in said[-1]


def test_the_command_names_a_python_that_lacks_torch(tmp_path, monkeypatch):
    kit = prepared(tmp_path, monkeypatch)
    code, said = run_setup(tmp_path, kit, lambda *_: 1, monkeypatch)
    assert code == 1
    assert "--judge-python" in said[-1]


def test_the_command_names_a_missing_merge_script(tmp_path, monkeypatch):
    kit = prepared(tmp_path, monkeypatch)
    (tmp_path / "routea" / "merge_adapter_torch.py").unlink()
    code, said = run_setup(tmp_path, kit, lambda *_: 0, monkeypatch)
    assert code == 1
    assert "merge_adapter_torch.py is not here" in said[-1]


@pytest.mark.parametrize("text", ["{not json", "[1]"])
def test_an_unreadable_base_config_is_named(tmp_path, text):
    base = make_base(tmp_path / "b")
    (base / "config.json").write_text(text)
    with pytest.raises(setup.KitSetupError, match="config.json"):
        setup.check_base(base)


def test_an_older_base_folder_is_replaced_by_the_merge(tmp_path, monkeypatch):
    kit = prepared(tmp_path, monkeypatch)
    (kit / "base").mkdir(parents=True)
    (kit / "base" / "stale.txt").write_text("old")

    def runner(python, args, log, extra):
        out = tmp_path / args[args.index("--out") + 1]
        out.mkdir(parents=True)
        (out / "config.json").write_text("{}")
        return 0

    inputs = setup.SetupInputs(tmp_path / "base", tmp_path / "files", kit, "python3")
    setup.merge_kit(inputs, runner, tmp_path / "merge.py", lambda line: None)
    assert not (kit / "base" / "stale.txt").exists()

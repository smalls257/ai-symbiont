"""Route B nightly end to end against a fake training host: fake ssh, scp, docker, curl, trainer.

The fake ssh runs the host step locally, so the real `ops/routeb_nightly_host.sh` and the real
`ops/gpu_run.sh` run against a fake `llama` container whose Running flag lives in a file, a fake
router that lists the preset's sections while the container runs, a stand-in training job and a
stand-in verifier. History is synthetic (scripts/routea/demo_sessions.py); no GPU, no network.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.periphery  # runs shell scripts, touches the disk

ROOT = Path(__file__).resolve().parents[2]
ROUTEB = ROOT / "scripts" / "routeb"
PLAIN = "Muse-Glimmer-30B-KQuant-17GB-Q4_K_M"
PERSONAL = "Muse-Glimmer-30B-demo-shop"
PRESET = f"""; router preset (synthetic)
[{PLAIN}]
model = /models/glimmer-q4.gguf
ctx-size = 32768
"""

FAKE_SSH = """#!/usr/bin/env bash
while [[ $1 == -o ]]; do shift 2; done
echo "ssh $1" >> "$FAKE_CALLS"
shift
exec bash -c "$*"
"""
FAKE_SCP = """#!/usr/bin/env bash
files=()
while [[ $# -gt 0 ]]; do
  case $1 in -o) shift 2 ;; -q | -r) shift ;; *) files+=("$1"); shift ;; esac
done
last=$((${#files[@]} - 1))
echo "scp ${files[$last]}" >> "$FAKE_CALLS"
cp -R "${files[@]:0:$last}" "${files[$last]#*:}"
"""
FAKE_DOCKER = """#!/usr/bin/env bash
echo "docker $*" >> "$FAKE_CALLS"
case "$1" in
  inspect) cat "$FAKE_DOCKER_STATE" ;;
  stop) echo false > "$FAKE_DOCKER_STATE" ;;
  start | restart) echo true > "$FAKE_DOCKER_STATE" ;;
  *) exit 99 ;;
esac
"""
FAKE_CURL = """#!/usr/bin/env python3
import json, os, sys
if open(os.environ["FAKE_DOCKER_STATE"]).read().strip() != "true":
    sys.exit(7)
text = open(os.environ["ROUTEB_PRESET"]).read()
broken = os.environ.get("FAKE_BREAK_NAME")
if broken and f"[{broken}]" in text:
    sys.exit(22)
names = [line.strip()[1:-1] for line in text.splitlines() if line.strip().startswith("[")]
print(json.dumps({"data": [{"id": name} for name in names]}))
"""
FAKE_FLOCK = """#!/usr/bin/env python3
import fcntl, sys
fcntl.flock(int(sys.argv[-1]), fcntl.LOCK_EX | fcntl.LOCK_NB)
"""
FAKE_TRAIN_JOB = """#!/usr/bin/env bash
work=$1 set=$2
test -s "$work/train/$set/train.jsonl" || exit 66
echo "train $set llama=$(cat "$FAKE_DOCKER_STATE") start_from=${ROUTEB_START_FROM:-none}" \
  >> "$FAKE_CALLS"
[[ -z ${FAKE_TRAIN_FAIL:-} ]] || exit 3
mkdir -p "$work/adapters/$set" && touch "$work/adapters/$set/.done"
echo gguf > "$ROUTEB_SERVE_DIR/glimmer-$set.gguf"
"""
# Stands in for ROUTEB_PY running verify_glimmer_models.py: checks what the real one checks
# through the router (plain has no LoRA, the personal name has one) from the preset itself.
FAKE_PYTHON = """#!/usr/bin/env python3
import os, sys
args = sys.argv[2:]
value = lambda flag: args[args.index(flag) + 1]
sections, name = {}, None
for line in open(os.environ["ROUTEB_PRESET"]):
    line = line.strip()
    if line.startswith("["):
        name = line[1:-1]
        sections[name] = []
    elif name and "=" in line:
        sections[name].append(line.split("=")[0].strip())
questions = open(os.path.join(value("--work"), "questions.jsonl")).read().splitlines()
with open(os.environ["FAKE_CALLS"], "a") as calls:
    calls.write(f"verify {value('--adapter')} questions={len(questions)}\\n")
plain_ok = "lora" not in sections[value("--plain")]
personal_ok = "lora" in sections.get(value("--adapter"), [])
sys.exit(0 if plain_ok and personal_ok and not os.environ.get("FAKE_VERIFY_FAIL") else 1)
"""


def load(name, directory=ROUTEB):
    spec = importlib.util.spec_from_file_location(name, directory / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def forget_loaded_modules(monkeypatch):
    monkeypatch.syspath_prepend(str(ROUTEB))
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        del sys.modules[name]


class Host:
    """The fake training host's files and the calls every fake recorded."""

    def __init__(self, tmp: Path):
        self.root = tmp / "host"
        self.preset = self.root / "presets.ini"
        self.serve = self.root / "serve"
        self.work = self.root / "nightly"
        self.state = tmp / "llama-running"
        self.calls = tmp / "calls"
        self.serve.mkdir(parents=True)
        self.preset.write_text(PRESET)
        self.state.write_text("true\n")
        self.calls.touch()

    def log(self) -> list[str]:
        return self.calls.read_text().splitlines()


def fakes(tmp: Path, host: Host) -> Path:
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    scripts = {"ssh": FAKE_SSH, "scp": FAKE_SCP, "docker": FAKE_DOCKER, "curl": FAKE_CURL}
    scripts |= {"flock": FAKE_FLOCK, "train_job": FAKE_TRAIN_JOB, "python": FAKE_PYTHON}
    for name, text in scripts.items():
        (bin_dir / name).write_text(text)
        (bin_dir / name).chmod(0o755)
    (tmp / "other").mkdir()
    env = {
        "ROUTEB_PRESET": host.preset,
        "ROUTEB_GLIMMER_URL": "http://glimmer.invalid",
        "ROUTEB_PLAIN_MODEL": PLAIN,
        "ROUTEB_SERVE_DIR": host.serve,
        "ROUTEB_SERVE_DIR_IN_CONTAINER": "/adapters",
        "ROUTEB_PY": bin_dir / "python",
        "ROUTEB_SNAPSHOT": host.root / "snapshot",
        "ROUTEB_TRAIN_JOB": bin_dir / "train_job",
        "ROUTEB_HEALTH_SECONDS": 2,
        "ROUTEB_HEALTH_POLL": 1,
        "GPU_RUN_LOG": tmp / "gpu_run.log",
        "GPU_RUN_LOCK": tmp / "gpu_run.lock",
        "GPU_RUN_FOREIGN_LOCKS": tmp / "other" / "gpu.lock",
    }
    env_file = host.root / "nightly.env"
    env_file.write_text("".join(f"{key}={value}\n" for key, value in env.items()))
    return bin_dir


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """A fake host, the fakes on PATH, a config, synthetic history; returns a night runner."""
    host = Host(tmp_path)
    bin_dir = fakes(tmp_path, host)
    monkeypatch.setenv("PATH", f"{bin_dir}:{Path(sys.executable).parent}:/usr/bin:/bin")
    monkeypatch.setenv("FAKE_CALLS", str(host.calls))
    monkeypatch.setenv("FAKE_DOCKER_STATE", str(host.state))
    history = tmp_path / "history"
    history.mkdir()
    write_sessions(history / "day1.jsonl", "demo-shop-1", "demo-shop-2")
    data = tmp_path / "data"
    config = tmp_path / "nightly.toml"
    config.write_text(
        f'data_dir = "{data}"\n[host]\nssh = "trainer"\ncheckout = "{ROOT}"\n'
        f'env_file = "{host.root / "nightly.env"}"\nwork_root = "{host.work}"\n'
        f'[[repo]]\nname = "demo-shop"\nsources = ["openhands={history}/*.jsonl"]\n'
    )
    nightly = load("nightly")
    stamps = iter(f"2026102{day}T020000Z" for day in range(1, 10))
    monkeypatch.setattr(nightly.time, "strftime", lambda *_: next(stamps))

    def night(*extra):
        return nightly.main(["--config", str(config), *extra])

    return host, data, history, night


def write_sessions(path: Path, *session_ids: str):
    demo = load("demo_sessions", ROOT / "scripts" / "routea")
    rows = [demo.trajectory(sid, demo.SESSIONS[sid]) for sid in session_ids]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def stored(data: Path):
    from symbiont.store.local import Store

    return Store.open(data / "store.db").lessons("demo-shop")


def test_a_night_trains_installs_verifies_and_forgets(rig, capsys):
    host, data, _, night = rig
    assert night() == 0
    out = capsys.readouterr().out
    for number, step in enumerate(load("nightly").STEPS, start=1):
        assert f"nightly demo-shop: [{number}/8] {step}:" in out
    assert "learned 2 lessons" in out
    preset = host.preset.read_text()
    assert preset.startswith(PRESET)  # plain section and comment untouched
    assert f"[{PERSONAL}]\nmodel = /models/glimmer-q4.gguf\nctx-size = 32768\n" in preset
    assert "lora = /adapters/glimmer-demo-shop-20261021T020000Z.gguf" in preset
    log = host.log()
    assert "train demo-shop-20261021T020000Z llama=false start_from=none" in log  # paused
    assert f"verify {PERSONAL} questions=2" in log
    assert host.state.read_text().strip() == "true"
    assert stored(data) == []
    manifest = json.loads((data / "manifests/routeb-demo-shop-20261021T020000Z.json").read_text())
    assert manifest["counts"] == {"lessons": 2, "source_sessions": 2}
    work = host.work / "demo-shop" / "20261021T020000Z"
    assert not (work / "train").exists() and not (work / "questions.jsonl").exists()
    assert not (data / "nightly" / "work").exists() or not any((data / "nightly/work").iterdir())


def test_the_next_night_learns_only_new_sessions_and_continues_the_adapter(rig, capsys):
    host, data, history, night = rig
    assert night() == 0
    assert night() == 0  # same logs: re-mined lessons are already trained
    assert "nothing new to learn; Glimmer untouched" in capsys.readouterr().out
    write_sessions(history / "day3.jsonl", "demo-shop-3")
    assert night() == 0
    first = host.work / "demo-shop/20261021T020000Z/adapters/demo-shop-20261021T020000Z"
    assert f"train demo-shop-20261023T020000Z llama=false start_from={first}" in host.log()
    assert "glimmer-demo-shop-20261023T020000Z.gguf" in host.preset.read_text()
    assert host.preset.read_text().count(f"[{PERSONAL}]") == 1


def test_a_failed_verify_restores_the_last_good_preset_and_forgets_nothing(
    rig, capsys, monkeypatch
):
    host, data, _, night = rig
    monkeypatch.setenv("FAKE_VERIFY_FAIL", "1")
    assert night() == 1
    out = capsys.readouterr().out
    assert "FAILED host step 'verify' failed with exit 1" in out
    assert host.preset.read_text() == PRESET
    assert host.state.read_text().strip() == "true"
    assert len(stored(data)) == 2
    assert not (host.work / "demo-shop/20261021T020000Z/train").exists()


def test_a_failed_training_leaves_glimmer_up_on_its_preset(rig, capsys, monkeypatch):
    host, data, _, night = rig
    monkeypatch.setenv("FAKE_TRAIN_FAIL", "1")
    assert night() == 1
    assert "FAILED host step 'train' failed with exit 1" in capsys.readouterr().out
    assert host.preset.read_text() == PRESET and host.state.read_text().strip() == "true"
    assert len(stored(data)) == 2
    assert not any("install" in call or "verify" in call for call in host.log())


def test_glimmer_not_coming_back_with_the_new_name_rolls_the_preset_back(rig, capsys, monkeypatch):
    host, data, _, night = rig
    monkeypatch.setenv("FAKE_BREAK_NAME", PERSONAL)
    assert night() == 1
    assert "FAILED host step 'install' failed with exit 1" in capsys.readouterr().out
    assert host.preset.read_text() == PRESET and host.state.read_text().strip() == "true"
    assert len(stored(data)) == 2


def test_a_dry_run_prints_every_step_and_changes_nothing(rig, capsys):
    host, data, history, night = rig
    from symbiont import cli

    log = sorted(history.glob("*.jsonl"))[0]
    argv = ["mine", "--project", "demo-shop", "--data-dir", str(data)]
    assert cli.main([*argv, "--source", f"openhands={log}"]) == 0
    capsys.readouterr()
    assert night("--dry-run") == 0
    out = capsys.readouterr().out
    for step in ("train", "install", "verify", "clean"):
        assert f"routeb_nightly_host.sh --env {host.root / 'nightly.env'} {step}" in out
    assert "would run: scp" in out
    assert host.log() == [] and host.preset.read_text() == PRESET
    assert len(stored(data)) == 2 and not (data / "manifests").exists()


def test_a_glob_that_matches_nothing_stops_the_night_before_the_host(rig, capsys, tmp_path):
    host, data, history, night = rig
    for log in history.glob("*.jsonl"):
        log.unlink()
    assert night() == 1
    assert "matches no file" in capsys.readouterr().out
    assert host.log() == []


def test_a_bad_config_exits_2_naming_the_key(tmp_path, capsys):
    config = tmp_path / "nightly.toml"
    config.write_text('[host]\nssh = "trainer"\n[[repo]]\nname = "demo"\n')
    assert load("nightly").main(["--config", str(config)]) == 2
    assert "'checkout' must be a non-empty string" in capsys.readouterr().err

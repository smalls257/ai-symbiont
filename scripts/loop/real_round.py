"""One real round from a config file outside the repo; called by `run_loop.py round --go` only.

The config names hosts by ssh alias and paths on this machine; nothing here guesses one. A
missing key raises `KeyError` naming it. See `loop.example.toml`.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from script_paths import add_script_dirs

add_script_dirs()

from coding_sqlglot import CodingPaths, CodingSqlglot  # noqa: E402  needs the script dirs
from freedoom import Freedoom, FreedoomPaths  # noqa: E402
from learners import (  # noqa: E402
    BaseArm,
    GlimmerAdapterLearner,
    Learner,
    Route,
    Start,
    WarnerAndMemoryLearner,
)
from ledger import Ledger, curve, load, save  # noqa: E402
from nightly_config import HostConfig  # noqa: E402
from nightly_host import TrainingHost  # noqa: E402
from round_runner import LoopSettings, RoundContext, run_round  # noqa: E402
from runner import LocalRunner  # noqa: E402
from trainer import HostTrainer  # noqa: E402
from training_plan import TrainMode  # noqa: E402


def domain_from(name: str, raw: dict[str, Any]) -> CodingSqlglot | Freedoom:
    """The plugin for `name`, from its config table."""
    table = raw[name]
    if name == "coding-sqlglot":
        coding = CodingPaths(
            Path(table["workdir"]).expanduser(),
            Path(table["split"]).expanduser(),
            Path(table["clone"]).expanduser(),
            table.get("python", "python"),
        )
        return CodingSqlglot(coding, LocalRunner())
    prereg = table.get("prereg")
    paths = FreedoomPaths(
        Path(table["repo"]).expanduser(),
        Path(table["episodes"]).expanduser(),
        Path(prereg).expanduser() if prereg else None,
    )
    return Freedoom(paths, LocalRunner())


def learner_from(raw: dict[str, Any], plain: str, state: Path) -> Learner:
    """The route's learner and its start (plain, or the configured shared habits base)."""
    route, start = Route(raw["route"]), Start(raw["start"])
    base = BaseArm(plain)
    if start is Start.SHARED_HABITS:
        table = raw["base"]
        base = BaseArm(table["arm"], {k: v for k, v in table.items() if k != "arm"})
    if route is Route.WARNER_AND_MEMORY:
        return WarnerAndMemoryLearner(start, base)
    host = raw["host"]
    config = HostConfig(host["ssh"], host["checkout"], host["env_file"], host["work_root"])
    trainer = HostTrainer(TrainingHost(config), state / "rows", f"{host['work_root']}/loop")
    return GlimmerAdapterLearner(trainer, start, base)


def run_real_round(domain_name: str, config: Path, state: Path) -> int:
    """Run the next round of one domain under the configured route and start."""
    raw = tomllib.loads(config.read_text(encoding="utf-8"))
    domain = domain_from(domain_name, raw)
    learner = learner_from(raw, domain.plain_model, state)
    key = f"{domain.name}/{learner.route}/{learner.start}"
    ledger = load(state, key) or Ledger.declare(
        domain.name, domain.held_out(), str(learner.route), str(learner.start)
    )
    settings = LoopSettings(train_mode=TrainMode(raw.get("train_mode", "from-scratch")))
    run_round(RoundContext(domain, learner, ledger, settings))
    save(state, ledger)
    print(curve(ledger))
    return 0

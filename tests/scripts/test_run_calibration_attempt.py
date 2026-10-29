"""A patch assigned before a later failure in _attempt is still returned for grading."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

CALIBRATION = Path(__file__).resolve().parents[2] / "scripts" / "calibration"
STUBBED = (
    "yaml",
    "litellm",
    "litellm.exceptions",
    "minisweagent",
    "minisweagent.agents",
    "minisweagent.agents.default",
    "minisweagent.config",
    "minisweagent.environments",
    "minisweagent.environments.docker",
    "minisweagent.models",
    "minisweagent.models.litellm_model",
)


class ExplodingPatch(str):
    def strip(self, *args):
        raise RuntimeError("raised after the patch was assigned")


def _load(monkeypatch):
    for name in STUBBED:
        monkeypatch.setitem(sys.modules, name, MagicMock())
    monkeypatch.syspath_prepend(str(CALIBRATION))
    spec = importlib.util.spec_from_file_location(
        "run_calibration_under_test", CALIBRATION / "run_calibration.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_patch_assigned_before_a_raise_is_still_returned(monkeypatch, tmp_path):
    module = _load(monkeypatch)
    agent = MagicMock(n_calls=1, messages=[])
    agent.run.return_value = {"exit_status": "Submitted", "submission": ExplodingPatch("diff")}
    monkeypatch.setattr(module, "DefaultAgent", lambda *args, **kwargs: agent)
    monkeypatch.setattr(module, "agent_config", lambda setting: ({}, {}))
    monkeypatch.setattr(module, "agent_model", lambda setting, model_cfg, rec: MagicMock())
    monkeypatch.setattr(module, "_open_environment", MagicMock)
    monkeypatch.setattr(module, "_prepare_checkout", lambda env, row: None)
    rec: dict = {}
    patch = module._attempt({"problem_statement": "x"}, None, tmp_path / "t.json", rec, 0.0)
    assert patch == "diff", rec
    assert rec["error_kind"] == "infra"

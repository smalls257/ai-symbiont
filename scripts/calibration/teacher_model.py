"""Teacher runs: mini-SWE-agent with Muse Spark or Wonder as the model, through symbiont.egress.

Every model turn is one `SparkSession.converse` call, so it is privacy-checked, priced into the one
spend ledger and stopped by the total and per-run caps before it is sent. Only public benchmark
rows are declared as provenance. Teacher runs are for EARLIER tasks only; the driver refuses any
test-set task before the first call.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum

import litellm
from minisweagent.models.litellm_model import LitellmModel
from minisweagent.models.utils.actions_toolcall import BASH_TOOL

from symbiont.egress import EgressRefusedError
from symbiont.egress.credentials import load_meta_key
from symbiont.egress.policy import Endpoint
from symbiont.egress.spark import Effort, SparkSession, _usage_from
from symbiont.egress.spend import SpendCapError, Tier, caps_from_environment, cost_usd
from symbiont.records.schema import Provenance

RUN_CAP_VARIABLE = "SYMBIONT_TEACHER_RUN_CAP_USD"
DEFAULT_RUN_CAP_DOLLARS = 0.5  # one 75-step run is about $0.07-0.10 on Contributor [hypothesis]
MAX_TOKENS = 8192  # room for hidden reasoning plus a tool call
HISTORY_KEYS = ("role", "content", "tool_calls", "tool_call_id", "name")
PUBLIC_ROWS = Provenance(
    dataset="swe-rebench-and-swe-bench-public", license="public", spark_safe=True
)


class Teacher(StrEnum):
    """Which remote model plays the agent."""

    SPARK = "spark"
    WONDER = "wonder"


@dataclass(frozen=True)
class TeacherSpec:
    """Model name, price tier and egress endpoint of one teacher."""

    model: str
    tier: Tier
    endpoint: Endpoint


# Model ids from api.meta.ai/v1/models (progress.md 2026-10-28 20:10). Wonder has no contributor
# variant listed, so it is billed on the standard price list, which is UNCONFIRMED [hypothesis].
SPECS = {
    Teacher.SPARK: TeacherSpec(
        "muse-spark-1.3-contributor", Tier.CONTRIBUTOR, Endpoint.CONTRIBUTOR
    ),
    Teacher.WONDER: TeacherSpec("muse-wonder-1.0", Tier.STANDARD, Endpoint.WONDER),
}


def history(messages: list[dict]) -> list[dict]:
    """The chat history in the plain OpenAI shape; agent bookkeeping fields stay home."""
    return [{key: msg[key] for key in HISTORY_KEYS if msg.get(key) is not None} for msg in messages]


class TeacherAgentModel(LitellmModel):
    """mini-SWE-agent's model with every turn sent through one capped Spark session."""

    abort_exceptions = [*LitellmModel.abort_exceptions, SpendCapError, EgressRefusedError]

    def __init__(self, *, session: SparkSession, label: str, **kwargs):
        super().__init__(**kwargs)
        self.session, self.label, self.turn = session, label, 0

    def _query(self, messages: list[dict], **kwargs):
        self.turn += 1
        out = self.session.converse(
            history(messages), [BASH_TOOL], Effort.LOW, f"{self.label}-t{self.turn}"
        )
        return litellm.ModelResponse(**out)

    def _calculate_cost(self, response) -> dict[str, float]:
        usage = _usage_from(response.model_dump())
        return {"cost": cost_usd(self.session.tier, usage)}


def run_cap_usd() -> float:
    """The per-run cap from SYMBIONT_TEACHER_RUN_CAP_USD; raises ValueError if unreadable."""
    raw = os.environ.get(RUN_CAP_VARIABLE)
    try:
        return float(raw) if raw else DEFAULT_RUN_CAP_DOLLARS
    except ValueError:
        raise ValueError(f"{RUN_CAP_VARIABLE} must be dollars, got {raw!r}") from None


def teacher_model(teacher: Teacher, run_label: str, model_cfg: dict) -> TeacherAgentModel:
    """A capped teacher model for one run; the ledger run name is `run_label`."""
    spec = SPECS[teacher]
    session = SparkSession(
        model=spec.model,
        tier=spec.tier,
        run=run_label,
        caps=caps_from_environment(run_cap_usd()),
        key=load_meta_key(),
        provenance=(PUBLIC_ROWS,),
        endpoint=spec.endpoint,
        turn_max_tokens=MAX_TOKENS,
    )
    config = model_cfg | {"model_name": spec.model, "model_kwargs": {}}
    return TeacherAgentModel(session=session, label=run_label, **config)

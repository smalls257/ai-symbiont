"""Reply-function factories the engine player can hand to worker processes (picklable).

A worker builds its own Spark session from the run name and caps, so no key or connection crosses
a process boundary; the spend ledger file is shared, which is why a run cap holds across workers
(it can be overshot by the calls already in flight, never skipped).
"""

from dataclasses import dataclass

from symbiont.act1.card_genome import Card
from symbiont.act1.game_fitness import Case
from symbiont.act1.glimmer import ReplyFn
from symbiont.act1.policies import policy_named
from symbiont.act1.spark_player import spark_reply_fn
from symbiont.egress.credentials import load_meta_key
from symbiont.egress.spark import Effort, SparkSession
from symbiont.egress.spend import Tier, caps_from_environment
from symbiont.records.schema import Provenance

MODEL = "muse-spark-1.3-contributor"
# Freedoom self-play on BSD-3 levels: Spark-safe by construction (episode_records.PROVENANCE).
PROVENANCE = Provenance(dataset="act1-freedoom2-selfplay", license="BSD-3-Clause", spark_safe=True)


def spark_session(run: str, run_cap: float) -> SparkSession:
    """A session for one run: contributor tier, the run's cap inside the total cap."""
    return SparkSession(
        MODEL, Tier.CONTRIBUTOR, run, caps_from_environment(run_cap), load_meta_key(),
        provenance=(PROVENANCE,),
    )  # fmt: skip


@dataclass(frozen=True)
class SparkPlayers:
    """Plays with Muse Spark at one reasoning effort; labels every call by phase and card."""

    run: str
    run_cap: float
    effort: Effort

    def __call__(self, card: Card, case: Case) -> ReplyFn:
        """The reply function for one game."""
        label = f"evolve/{self.run}/play/{card.card_id}"
        return spark_reply_fn(spark_session(self.run, self.run_cap), self.effort, label)


@dataclass(frozen=True)
class ScriptedPlayers:
    """Plays with a named scripted policy (no model, no cost)."""

    policy: str

    def __call__(self, card: Card, case: Case) -> ReplyFn:
        """The policy's reply function, seeded by the case."""
        return policy_named(self.policy, case.seed).reply

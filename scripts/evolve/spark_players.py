"""Reply-function factories the engine player can hand to worker processes (picklable).

A worker builds its own Spark session from the run name and caps, so no key or connection crosses
a process boundary; the spend ledger file is shared, which is why a run cap holds across workers
(it can be overshot by the calls already in flight, never skipped).
"""

import logging
import re
import time
import urllib.error
from collections.abc import Callable
from dataclasses import dataclass, replace

from symbiont.act1.card_genome import Card
from symbiont.act1.card_prompt import CardPlacement, system_rules
from symbiont.act1.game_fitness import Case
from symbiont.act1.glimmer import Reply, ReplyFn
from symbiont.act1.policies import policy_named
from symbiont.act1.spark_player import spark_reply_fn
from symbiont.egress.credentials import load_meta_key
from symbiont.egress.spark import (
    DEFAULT_MAX_TOKENS,
    Effort,
    SparkApiError,
    SparkReply,
    SparkSession,
)
from symbiont.egress.spend import Tier, caps_from_environment
from symbiont.records.schema import Provenance

MODEL = "muse-spark-1.3-contributor"
# Freedoom self-play on BSD-3 levels: Spark-safe by construction (episode_records.PROVENANCE).
PROVENANCE = Provenance(dataset="act1-freedoom2-selfplay", license="BSD-3-Clause", spark_safe=True)


log = logging.getLogger(__name__)
# Server and network trouble that a short wait can clear; anything else (a 400, a 401, a refusal)
# is ours to fix and is raised at once.
RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
# About four minutes in all: long enough for a short network or server outage to pass.
RETRY_WAITS_S = (2.0, 5.0, 12.0, 30.0, 60.0, 120.0)
STATUS = re.compile(r"^status (\d+)")


def is_transient(error: Exception) -> bool:
    """Whether waiting and asking again could help: a busy or failing server, a dropped line."""
    if isinstance(error, SparkApiError):
        found = STATUS.match(str(error))
        return bool(found) and int(found.group(1)) in RETRY_STATUSES
    return isinstance(error, urllib.error.URLError | TimeoutError | ConnectionError)


def with_retries(
    reply_fn: ReplyFn,
    waits: tuple[float, ...] = RETRY_WAITS_S,
    sleep: Callable[[float], None] = time.sleep,
) -> ReplyFn:
    """Ask again after a transient failure with growing waits; when they run out, raise it.

    Each retry is logged (attempt, error class) but never the prompt.
    """

    def reply(prompt: str) -> Reply:
        for attempt, wait in enumerate((*waits, None), start=1):
            try:
                return reply_fn(prompt)
            except Exception as error:
                if wait is None or not is_transient(error):
                    raise
                log.warning(
                    "transient %s on attempt %d; waiting %.0fs", type(error).__name__, attempt, wait
                )
                sleep(wait)
        raise AssertionError("unreachable: the last attempt returns or raises")

    return reply


@dataclass(frozen=True)
class RetryingSession:
    """A Spark session whose `chat` waits and asks again after a transient failure.

    The author and the judge use this: a network blip must not end hours of evolution. Anything
    that is not transient, and a transient error that outlasts the waits, is raised.
    """

    inner: SparkSession
    waits: tuple[float, ...] = RETRY_WAITS_S
    sleep: Callable[[float], None] = time.sleep

    @property
    def run(self) -> str:
        """The run name the ledger lines carry."""
        return self.inner.run

    def chat(
        self, prompt: str, effort: Effort, label: str, max_tokens: int | None = None
    ) -> SparkReply:
        """The inner session's reply, after retries."""
        extra = {} if max_tokens is None else {"max_tokens": max_tokens}
        for attempt, wait in enumerate((*self.waits, None), start=1):
            try:
                return self.inner.chat(prompt, effort, label, **extra)
            except Exception as error:
                if wait is None or not is_transient(error):
                    raise
                log.warning(
                    "transient %s on attempt %d; waiting %.0fs", type(error).__name__, attempt, wait
                )
                self.sleep(wait)
        raise AssertionError("unreachable: the last attempt returns or raises")


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
    temperature: float | None = None
    max_tokens: int = DEFAULT_MAX_TOKENS
    placement: CardPlacement = CardPlacement.PROMPT_PREFIX

    def __call__(self, card: Card, case: Case) -> ReplyFn:
        """The reply function for one game; the card goes where `placement` says."""
        label = f"evolve/{self.run}/play/{card.card_id}"
        rules = system_rules(card) if self.placement == CardPlacement.SYSTEM_RULES else None
        session = replace(
            spark_session(self.run, self.run_cap), temperature=self.temperature, system=rules
        )
        return with_retries(spark_reply_fn(session, self.effort, label, self.max_tokens))


@dataclass(frozen=True)
class ScriptedPlayers:
    """Plays with a named scripted policy (no model, no cost)."""

    policy: str

    def __call__(self, card: Card, case: Case) -> ReplyFn:
        """The policy's reply function, seeded by the case."""
        return policy_named(self.policy, case.seed).reply

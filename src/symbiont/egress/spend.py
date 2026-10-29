"""The spend ledger and its caps: every priced remote call is recorded, and a cap stops the next.

`check_before_call` raises `SpendCapError` before the request is built, and an unreadable ledger
line raises rather than under-counting. Counts, model and cost only, never prompt or reply text.
With several games in flight a cap can be overshot by the calls already on the wire; never skipped.
"""

import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

DEFAULT_LEDGER = Path.home() / "symbiont-runs" / "spend" / "ledger.jsonl"
CAP_VARIABLE = "SYMBIONT_SPEND_CAP_USD"
DEFAULT_TOTAL_CAP_DOLLARS = 15.0  # the owner's hackathon budget for Spark and Contributor calls
PER_MILLION = 1_000_000


class Tier(StrEnum):
    """Which price list a call is billed on."""

    CONTRIBUTOR = "contributor"
    STANDARD = "standard"


@dataclass(frozen=True)
class Price:
    """Dollars per million tokens."""

    input_usd: float
    output_usd: float
    cached_usd: float


# Source: the owner's note (contributor $0.10 in / $0.20 out) and third-party reports for the
# standard tier ($1.25 in / $4.25 out, cached $0.15), all UNCONFIRMED [hypothesis]. Cached tokens
# are billed at the input rate (an upper bound); reasoning tokens count inside completion tokens.
PRICES = {
    Tier.CONTRIBUTOR: Price(input_usd=0.10, output_usd=0.20, cached_usd=0.10),
    Tier.STANDARD: Price(input_usd=1.25, output_usd=4.25, cached_usd=0.15),
}


class SpendCapError(RuntimeError):
    """A cap is reached; raised before the call that would exceed it is sent."""


@dataclass(frozen=True)
class Usage:
    """Token counts the server reported for one call."""

    prompt: int
    cached: int
    completion: int
    reasoning: int


@dataclass(frozen=True)
class SpendCaps:
    """The hard cap over every run and the cap of this run (None: only the total applies)."""

    total_usd: float
    run_usd: float | None


@dataclass(frozen=True)
class LedgerEntry:
    """One priced call: who asked, which model and tier, the counts, the cost, the latency."""

    run: str
    label: str
    model: str
    tier: Tier
    usage: Usage
    cost_usd: float
    seconds: float
    error: str | None = None  # the status or error class of a call that failed; None: it succeeded


def cost_usd(tier: Tier, usage: Usage) -> float:
    """Dollar cost of one call from the price table."""
    price = PRICES[tier]
    fresh = usage.prompt - usage.cached
    return (
        fresh * price.input_usd
        + usage.cached * price.cached_usd
        + usage.completion * price.output_usd
    ) / PER_MILLION


def caps_from_environment(run_usd: float | None) -> SpendCaps:
    """The total cap from SYMBIONT_SPEND_CAP_USD (default $15). Raises ValueError if unreadable."""
    raw = os.environ.get(CAP_VARIABLE)
    if raw is None:
        return SpendCaps(DEFAULT_TOTAL_CAP_DOLLARS, run_usd)
    try:
        return SpendCaps(float(raw), run_usd)
    except ValueError:
        raise ValueError(f"{CAP_VARIABLE} must be a number of dollars, got {raw!r}") from None


class Ledger:
    """Append-only JSON lines; the file is the one source of truth, so processes share it."""

    def __init__(self, path: Path = DEFAULT_LEDGER):
        self._path = path
        self._lock = threading.Lock()

    def record(self, entry: LedgerEntry) -> None:
        """Append one line (counts and cost, no text)."""
        usage = asdict(entry.usage)
        line = {"ts": round(time.time(), 3), "run": entry.run, "label": entry.label,
                "model": entry.model, "tier": entry.tier.value, **usage,
                "cost_usd": entry.cost_usd, "seconds": round(entry.seconds, 3)}  # fmt: skip
        if entry.error is not None:
            line["error"] = entry.error
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(line) + "\n")

    def entries(self) -> list[dict[str, Any]]:
        """Every line; raises ValueError naming the line when one cannot be parsed."""
        if not self._path.exists():
            return []
        rows = []
        for number, text in enumerate(self._path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                rows.append(json.loads(text))
            except json.JSONDecodeError:
                raise ValueError(f"ledger {self._path} line {number} is not valid JSON") from None
        return rows

    def spent(self, run: str | None = None) -> float:
        """Dollars in the whole ledger, or in one run."""
        return float(
            sum(row["cost_usd"] for row in self.entries() if run is None or row["run"] == run)
        )

    def check_before_call(self, run: str, caps: SpendCaps) -> None:
        """Raise SpendCapError when the total or this run's cap is already reached."""
        total = self.spent()
        if total >= caps.total_usd:
            raise SpendCapError(f"total spend ${total:.4f} reached the cap ${caps.total_usd:.2f}")
        if caps.run_usd is not None and self.spent(run) >= caps.run_usd:
            raise SpendCapError(f"run {run!r} reached its cap ${caps.run_usd:.2f}")

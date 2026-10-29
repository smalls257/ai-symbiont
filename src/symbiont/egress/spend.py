"""The spend ledger and its caps: every call that leaves is recorded, and a cap stops the next.

`Ledger.reserve` holds a call's worst-case cost under a file lock together with the cap check,
so concurrent callers cannot overshoot; `settle` records the real or estimated cost. An
unreadable ledger line raises rather than under-counting. Counts, model and cost only, never text.
"""

import fcntl
import json
import os
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

DEFAULT_LEDGER = Path.home() / "symbiont-runs" / "spend" / "ledger.jsonl"
CAP_VARIABLE = "SYMBIONT_SPEND_CAP_USD"
DEFAULT_TOTAL_CAP_DOLLARS = 15.0  # the owner's hackathon budget for Spark and Contributor calls
PER_MILLION = 1_000_000
PHASE_RESERVED, PHASE_SETTLED, PHASE_RELEASED = "reserved", "settled", "released"


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
    estimated: bool = False  # True: the server reported no usage, so the counts are our estimate


def cost_usd(tier: Tier, usage: Usage) -> float:
    """Dollar cost of one call from the price table."""
    price = PRICES[tier]
    fresh = usage.prompt - usage.cached
    return (
        fresh * price.input_usd
        + usage.cached * price.cached_usd
        + usage.completion * price.output_usd
    ) / PER_MILLION


# English prose and code run about four bytes per token; assuming three over-counts the prompt,
# which is the safe side for a cap. A request that may have been generated is charged its full
# `max_tokens` of output.
BYTES_PER_TOKEN_FLOOR = 3


def estimate_usage(wire_bytes: int, max_tokens: int, *, generated: bool) -> Usage:
    """Conservative token counts for a call whose real usage is unknown.

    `generated` is False for a request the server rejected before generating (a 4xx): only the
    prompt is charged then.
    """
    prompt = -(-wire_bytes // BYTES_PER_TOKEN_FLOOR)
    return Usage(prompt=prompt, cached=0, completion=max_tokens if generated else 0, reasoning=0)


def estimate_call_usd(tier: Tier, wire_bytes: int, max_tokens: int) -> float:
    """Worst-case dollars of one call: the estimated prompt plus the full `max_tokens` of output."""
    return cost_usd(tier, estimate_usage(wire_bytes, max_tokens, generated=True))


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
    """Append-only JSON lines shared by every process; a call is reserved before it is sent.

    A reservation holds the worst-case cost of the next call, taken under a file lock together
    with the cap check, so concurrent callers cannot all pass the check and then overshoot. A
    settled line replaces its reservation at the real (or estimated) cost; a released one
    removes it. A crash between reserve and settle leaves the reservation: the safe side.
    """

    def __init__(self, path: Path = DEFAULT_LEDGER):
        """Point at the shared ledger file; nothing is created until the first write."""
        self._path = path
        self._lock = threading.Lock()

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        """Thread lock plus an flock on a sidecar file, so processes take turns too."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._path.with_name(self._path.name + ".lock").open("w") as guard:
            fcntl.flock(guard, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(guard, fcntl.LOCK_UN)

    def _append(self, line: dict[str, Any]) -> None:
        """Add one JSON line; callers hold the lock so lines never interleave."""
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line) + "\n")

    @staticmethod
    def _row(entry: LedgerEntry, call: str, phase: str) -> dict[str, Any]:
        """The ledger line for one entry: counts, cost and status, never any text."""
        row = {"ts": round(time.time(), 3), "call": call, "phase": phase, "run": entry.run,
               "label": entry.label, "model": entry.model, "tier": entry.tier.value,
               **asdict(entry.usage), "cost_usd": entry.cost_usd,
               "seconds": round(entry.seconds, 3), "estimated": entry.estimated}  # fmt: skip
        if entry.error is not None:
            row["error"] = entry.error
        return row

    def record(self, entry: LedgerEntry) -> None:
        """Append one settled line for a call that was never reserved (counts and cost only)."""
        with self._exclusive():
            self._append(self._row(entry, uuid.uuid4().hex, PHASE_SETTLED))

    def reserve(self, run: str, caps: SpendCaps, estimate_usd: float, label: str) -> str:
        """Check both caps including `estimate_usd`, then hold it; returns the call id.

        Raises SpendCapError when spent plus the estimate would pass the total or run cap.
        """
        with self._exclusive():
            total, in_run = self.spent(), self.spent(run)
            if total + estimate_usd >= caps.total_usd:
                raise SpendCapError(
                    f"total spend ${total:.4f} plus this call's worst case ${estimate_usd:.4f} "
                    f"would reach the cap ${caps.total_usd:.2f}"
                )
            if caps.run_usd is not None and in_run + estimate_usd >= caps.run_usd:
                raise SpendCapError(
                    f"run {run!r} spend ${in_run:.4f} plus this call's worst case "
                    f"${estimate_usd:.4f} would reach its cap ${caps.run_usd:.2f}"
                )
            call = uuid.uuid4().hex
            held = LedgerEntry(run, label, "", Tier.CONTRIBUTOR, Usage(0, 0, 0, 0), estimate_usd,
                               0.0, "reserved", estimated=True)  # fmt: skip
            self._append(self._row(held, call, PHASE_RESERVED))
            return call

    def settle(self, call: str, entry: LedgerEntry) -> None:
        """Replace the reservation `call` with the call's own line."""
        with self._exclusive():
            self._append(self._row(entry, call, PHASE_SETTLED))

    def release(self, call: str) -> None:
        """Drop a reservation for a call that never left the machine."""
        with self._exclusive():
            self._append({"call": call, "phase": PHASE_RELEASED})

    def entries(self) -> list[dict[str, Any]]:
        """One row per call (settled beats reserved; released calls vanish).

        Raises ValueError naming the line when one cannot be parsed.
        """
        if not self._path.exists():
            return []
        rows: dict[str, dict[str, Any]] = {}
        for number, text in enumerate(self._path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                row = json.loads(text)
            except json.JSONDecodeError:
                raise ValueError(f"ledger {self._path} line {number} is not valid JSON") from None
            call = row.get("call", f"legacy-{number}")
            if row.get("phase") == PHASE_RELEASED:
                rows.pop(call, None)
            elif row.get("phase") != PHASE_RESERVED or call not in rows:
                rows[call] = row
        return list(rows.values())

    def spent(self, run: str | None = None) -> float:
        """Dollars in the whole ledger (reservations included), or in one run."""
        rows = self.entries()
        return float(sum(row["cost_usd"] for row in rows if run is None or row["run"] == run))

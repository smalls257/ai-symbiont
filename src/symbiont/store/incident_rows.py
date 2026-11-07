"""Incidents as the JSON the incidents table stores, and back.

The table is replaced by every mining run (like lessons). The body holds the card's plain-language
sentences and a scrubbed example, never a record.
"""

import json
from dataclasses import asdict
from typing import Any

from symbiont.miner.incident_types import Incident, NoiseReason, Outcome
from symbiont.miner.painpoint import Signal

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    project TEXT NOT NULL, session_id TEXT NOT NULL, step INTEGER NOT NULL, body TEXT NOT NULL
);
"""


def incident_row(project: str, incident: Incident) -> tuple[str, str, int, str]:
    """The incidents-table row of one card."""
    body = json.dumps(asdict(incident), default=str)
    return (project, incident.session_id, incident.step, body)


def incident_from_json(body: str) -> Incident:
    """Rebuild a card from its stored JSON; a missing field raises KeyError naming it."""
    data: dict[str, Any] = json.loads(body)
    noise = data["noise"]
    return Incident(
        session_id=data["session_id"],
        step=data["step"],
        signal=Signal(data["signal"]),
        what_happened=data["what_happened"],
        first_wrong=data["first_wrong"],
        cost_steps=data["cost_steps"],
        what_fixed_it=data["what_fixed_it"],
        outcome=Outcome(data["outcome"]),
        noise=NoiseReason(noise) if noise else None,
        topic=data["topic"],
        files=tuple(data["files"]),
        situation=(data["situation"][0], data["situation"][1], data["situation"][2]),
        fingerprint=data["fingerprint"],
        example=data["example"],
        # Cards stored before the story lines carry none; the page falls back to the sentences.
        working_on=data.get("working_on", ""),
        broke=data.get("broke", ""),
        ended=data.get("ended", ""),
    )

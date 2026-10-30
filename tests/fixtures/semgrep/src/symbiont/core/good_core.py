"""Fixture: a pure core. No line here may be reported by any rule."""

import json
import math
import random
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Moment:
    at: datetime


def decay(moment: Moment, now: datetime, rate: float) -> float:
    return math.exp(-rate * (now - moment.at).total_seconds())


def seeded_roll(seed: int) -> float:
    return random.Random(seed).random()


def encode(value: dict) -> str:
    return json.dumps(value, sort_keys=True)

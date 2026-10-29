"""Move-failure injection: a seeded, pure decision to cut a scripted move short (pure).

The changed-world condition cuts some moves short (design section 5.2) so a lesson that only works
when every move runs to completion does not survive selection. The cut decision is a function of
(seed, move number), so a replay cuts the same moves with no clock and no global RNG; the engine
only applies the cap, and a cut move says so in its outcome text so a cut is never passed off as
the move's own result.
"""

import random
from dataclasses import dataclass
from enum import StrEnum

NORMAL_SKILL = 3
HARDER_SKILL = 4
# Design section 5.2: the share of moves cut short in the changed-world and harder conditions.
CUT_SHARE = 0.1  # [hypothesis] (design setting)


class CutSetting(StrEnum):
    """Whether moves are cut short in a game."""

    NONE = "none"
    TEN_PERCENT = "ten_percent"


@dataclass(frozen=True)
class MoveCuts:
    """Cuts a `share` of moves, decided by `seed` and the move's number within the episode."""

    share: float
    seed: int

    def __post_init__(self) -> None:
        """Refuse a share outside 0 to 1."""
        if not 0.0 <= self.share <= 1.0:
            raise ValueError(f"cut share {self.share} is outside 0 to 1")

    def tic_cap(self, move_number: int, max_tics: int) -> int | None:
        """None when the move runs normally, else a cap from 1 to half the move's tics."""
        rng = random.Random(f"{self.seed}:{move_number}")
        if rng.random() >= self.share:
            return None
        return rng.randint(1, max(1, max_tics // 2))


def cuts_for(setting: CutSetting, seed: int) -> MoveCuts | None:
    """The cuts for a game's setting; None for CutSetting.NONE."""
    if setting == CutSetting.NONE:
        return None
    return MoveCuts(share=CUT_SHARE, seed=seed)

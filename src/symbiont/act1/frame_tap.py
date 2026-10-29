"""A game wrapper that keeps screen frames and stops the episode at a tic budget (periphery).

Frames are taken from the engine after each real action and nowhere else, so a clip shows exactly
the tics played; a clip cut by its budget says so (`budget_spent`) instead of passing for an
episode that ended. Everything else the wrapped game offers is passed through.
"""

from typing import Any

import numpy as np


class FrameTap:
    """Wraps a ViZDoom game: every `stride`-th action's screen is kept until taken."""

    def __init__(self, game: Any, stride: int, tic_budget: int):
        """Wrap a game; keep every `stride`-th tic's screen and stop after `tic_budget` tics."""
        if stride < 1 or tic_budget < 1:
            raise ValueError(
                f"stride and tic_budget must be at least 1, got {stride}, {tic_budget}"
            )
        self._game = game
        self._stride = stride
        self._tic_budget = tic_budget
        self._tics = 0
        self._frames: list[np.ndarray] = []

    def __getattr__(self, name: str) -> Any:
        """Everything the tap does not override is the wrapped game's."""
        return getattr(self._game, name)

    @property
    def budget_spent(self) -> bool:
        """True when the tic budget, not the game, ended the episode."""
        return self._tics >= self._tic_budget

    def make_action(self, action: list[int]) -> float:
        """Play one tic; keep its screen when it falls on the stride."""
        reward = self._game.make_action(action)
        self._tics += 1
        if self._tics % self._stride == 0:
            self._keep_screen()
        return float(reward)

    def is_episode_finished(self) -> bool:
        """True at the game's own end or when the tic budget is spent."""
        return self.budget_spent or bool(self._game.is_episode_finished())

    def take_frames(self) -> list[np.ndarray]:
        """The frames kept since the last call (channels-first RGB), oldest first."""
        taken, self._frames = self._frames, []
        return taken

    def _keep_screen(self) -> None:
        """Keep the current screen, if the last action left one."""
        state = self._game.get_state()
        if state is not None:  # None: that action ended the episode, there is no screen to keep
            self._frames.append(np.array(state.screen_buffer))

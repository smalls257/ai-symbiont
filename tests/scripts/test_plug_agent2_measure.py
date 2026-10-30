"""PLUG-AGENT-2 stop rule: coded exactly as the prereg states it."""

import sys
from pathlib import Path

ROUTEA = Path(__file__).resolve().parents[2] / "scripts" / "routea"
sys.path.insert(0, str(ROUTEA))

from plug_agent2_measure import go_ahead, mde_points, probe_share  # noqa: E402


def test_mde_uses_the_frozen_sd():
    assert round(mde_points(38), 1) == 15.0


def test_the_rule_needs_every_condition():
    assert go_ahead(5, 0, 0.6, 38)
    assert not go_ahead(5, 1, 0.6, 38)  # a void among the probe points
    assert not go_ahead(4, 0, 0.6, 38)  # too few restored points
    assert not go_ahead(5, 0, 0.29, 38)  # nothing to prevent
    assert not go_ahead(5, 0, 0.6, 19)  # too few pooled points
    assert not go_ahead(5, 0, None, 38)


def test_probe_share_is_the_mean_of_per_point_shares():
    assert probe_share([[True, True, False], [False, False, False]]) == (2 / 3 + 0) / 2

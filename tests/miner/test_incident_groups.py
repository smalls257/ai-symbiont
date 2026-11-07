"""Incident groups: one per fingerprint, newest first, with noise only when every card is."""

from symbiont.miner.incident_groups import fingerprint_of, group_incidents
from symbiont.miner.incident_types import Incident, NoiseReason, Outcome
from symbiont.miner.painpoint import Signal


def card(session="s1", step=1, signal=Signal.FAILED_COMMAND, noise=None, fingerprint="", **kw):
    return Incident(
        session_id=session, step=step, signal=signal, what_happened="h", first_wrong="",
        cost_steps=0, what_fixed_it="f", outcome=Outcome.NEVER_FIXED, noise=noise, topic="",
        files=(), situation=("running", "pytest", "tests"), fingerprint=fingerprint, **kw,
    )  # fmt: skip


def failure(session, step=1, noise=None):
    return card(session, step, noise=noise, fingerprint="failure:pytest:ImportError")


def test_the_same_program_failing_the_same_way_is_one_group():
    groups = group_incidents(
        [failure("a"), failure("b"), card("c", fingerprint="failure:pytest:KeyError")], {}, {}
    )
    assert [(g.key, len(g.cards)) for g in groups] == [
        ("failure:pytest:ImportError", 2),
        ("failure:pytest:KeyError", 1),
    ]


def test_a_correction_joins_its_model_group_else_stands_alone():
    named = card("a", 4, Signal.CORRECTION)
    alone = card("b", 9, Signal.CORRECTION)
    groups = group_incidents([named, alone], {}, {("a", 4): "Use pnpm"})
    assert sorted(g.key for g in groups) == ["correction:Use pnpm", "correction:b:9"]


def test_the_key_does_not_depend_on_the_order_cards_were_mined():
    cards = [failure("a"), failure("b")]
    forward = group_incidents(cards, {}, {})
    backward = group_incidents(cards[::-1], {}, {})
    assert [g.key for g in forward] == [g.key for g in backward]


def test_a_group_is_noise_only_when_every_card_is():
    retry = NoiseReason.PLAIN_RETRY
    mixed = group_incidents([failure("a", noise=retry), failure("b")], {}, {})
    assert mixed[0].noise is None
    quiet = group_incidents(
        [
            failure("a", noise=retry),
            failure("b", noise=retry),
            failure("c", noise=NoiseReason.LOOK_AROUND),
        ],
        {},
        {},
    )
    assert quiet[0].noise is retry


def test_cards_run_newest_first_and_undated_ones_last():
    days = {"a": "2026-10-01", "b": "2026-10-20", "c": None}
    group = group_incidents([failure("a"), failure("c"), failure("b")], days, {})[0]
    assert [c.session_id for c in group.cards] == ["b", "a", "c"]


def test_empty_corrections_share_one_group_instead_of_flooding_the_inbox():
    empty = [card(s, 1, Signal.CORRECTION, NoiseReason.EMPTY_CORRECTION) for s in "abc"]
    assert len(group_incidents(empty, {}, {})) == 1
    assert fingerprint_of(empty[0], {}) == "correction:empty"

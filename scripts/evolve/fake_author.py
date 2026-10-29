"""Offline stand-ins for the model author and judge: deterministic edits, never a model."""

from symbiont.act1.card_genome import Card
from symbiont.act1.offline_author import OFFLINE_LESSONS, AllowAllJudge, OfflineAuthor

__all__ = ["AllowAllJudge", "OfflineAuthor", "dry_run_seed_cards"]


def dry_run_seed_cards() -> list[Card]:
    """Six seed cards for a dry run: the empty card first (the no-card floor), then five more."""
    pool = OFFLINE_LESSONS
    shapes = ([], [pool[0]], [pool[0], pool[3]], [pool[1]], [pool[2]], [pool[1], pool[2]])
    return [Card.of(lessons) for lessons in shapes]

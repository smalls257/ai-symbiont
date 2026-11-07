"""Group verdict sentences are the model's paid work: a re-mine must not empty them.

Failure guarded against: Silent Fallback (a re-mine that quietly drops sentences bills again).
"""

from datetime import date

import pytest

from symbiont.store.held_back import REPLACED_TABLES
from symbiont.store.local import Store

pytestmark = pytest.mark.periphery
DAY = date(2026, 11, 7)


def test_sentences_round_trip_per_project_and_a_rewrite_replaces(tmp_path):
    store = Store.open(tmp_path / "s.db")
    verdicts = store.review.verdicts

    verdicts.save("demo", {"k1": "Worth a look: one.", "k2": "Noise: two."}, DAY)
    verdicts.save("demo", {"k1": "Fixed in practice: three."}, DAY)

    assert verdicts.sentences("demo") == {"k1": "Fixed in practice: three.", "k2": "Noise: two."}
    assert verdicts.sentences("other") == {}


def test_the_table_is_developer_owned_and_survives_a_remine():
    assert "group_verdicts" not in REPLACED_TABLES

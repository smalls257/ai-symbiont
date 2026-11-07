"""Group verdict sentences: candidates, the checked save, the dataset refusal and the snapshot.

Failures guarded against: Silent Fallback (a bad or unknown-key sentence accepted, a dataset
history quietly offered to the session model) and Paper Tiger (a sentence saved but never shown).
"""

from dataclasses import replace
from datetime import date

import pytest

from record_builders import say, session, user
from symbiont.miner.incident_types import Incident, NoiseReason, Outcome
from symbiont.miner.painpoint import Signal
from symbiont.records.schema import dump_jsonl, load_jsonl
from symbiont.service.curation_routes import CurationRoutes
from symbiont.service.incident_view import incidents_snapshot
from symbiont.service.request_shapes import BadRequestError
from symbiont.service.summary_routes import SummaryRoutes
from symbiont.store.held_back import MiningOutcome
from symbiont.store.local import Source, Store
from symbiont.store.repos import RepoRegistry, RepoStance
from symbiont.store.settings import CorrectionSettings

pytestmark = pytest.mark.periphery
PROJECT = "demo"
REQUEST = {"project": PROJECT}
TODAY = date(2026, 11, 7)
WORTH = "Worth a look: two git calls ran in parallel; stop the race, not the lock."


def card(session_id, program="pytest", noise=None):
    return Incident(
        session_id=session_id, step=1, signal=Signal.FAILED_COMMAND,
        what_happened=f"The agent ran {program} and it failed.", first_wrong="", cost_steps=0,
        what_fixed_it="Edited app.py, then the command passed.", outcome=Outcome.FIXED_IN_CODE,
        noise=noise, topic="", files=("app.py",), situation=("running", program, "tests"),
        fingerprint=f"failure:{program}:boom", example=f"{program} tests",
    )  # fmt: skip


def read_jsonl(path, project):
    with open(path, encoding="utf-8") as fh:
        return iter(list(load_jsonl(fh)))


def rig(tmp_path, cards, extra_sources=()):
    store = Store.open(tmp_path / "s.db")
    registry = RepoRegistry(tmp_path)
    registry.record_stance(PROJECT, RepoStance.GIVEN)
    sources = []
    for reader in extra_sources:
        path = tmp_path / f"{reader}.jsonl"
        with path.open("w") as fh:
            dump_jsonl([replace(r, project=PROJECT) for r in session(user("hi"), say("ok"))], fh)
        sources.append(Source(PROJECT, reader, str(path)))
    store.mined.save(
        PROJECT, sources, MiningOutcome([], incidents=cards), held_out_tasks=frozenset()
    )
    readers = {"swe-chat": read_jsonl}
    curation = CurationRoutes(store, registry, lambda: CorrectionSettings(), readers)
    return SummaryRoutes(curation, store, readers, lambda: TODAY), store


def recurring_cards():
    return [card("a"), card("b"), card("c", "git"), card("d", "npm", NoiseReason.LOOK_AROUND)]


def test_candidates_offer_only_recurring_non_noise_groups_without_a_sentence(tmp_path):
    routes, store = rig(tmp_path, recurring_cards())

    answer = routes.verdict_candidates(REQUEST)

    (group,) = answer["candidates"]
    assert answer["remaining"] == 0 and group["sessions"] == 2 and group["times"] == 2
    assert len(group["examples"]) == 2 and group["examples"][0]["fixed"].startswith("Edited")
    assert {"key", "name", "happened", "fixed", "verdict", "badge"} <= set(group)
    routes.save_verdicts(
        {"project": PROJECT, "verdicts": [{"key": group["key"], "sentence": WORTH}]}
    )
    assert routes.verdict_candidates(REQUEST)["candidates"] == []


def test_a_saved_sentence_is_stored_and_shown_as_verdict_sentence(tmp_path):
    routes, store = rig(tmp_path, recurring_cards())
    before = incidents_snapshot(store, PROJECT)["groups"]
    assert {g["verdictSentence"] for g in before} == {None}
    key = next(g["key"] for g in before if g["recurring"])

    saved = routes.save_verdicts(
        {"project": PROJECT, "verdicts": [{"key": key, "sentence": WORTH}]}
    )

    assert saved == {"saved": 1}
    shown = {g["key"]: g["verdictSentence"] for g in incidents_snapshot(store, PROJECT)["groups"]}
    assert shown[key] == WORTH and list(shown.values()).count(None) == len(shown) - 1


@pytest.mark.parametrize(
    ("sentence", "message"),
    [
        ("Probably the lock.", "must start with"),
        (WORTH + " " + "x" * 220, "over 220"),
        ("Worth a look: one.\nTwo.", "one line"),
        ("", "must be text"),
    ],
)
def test_a_bad_sentence_is_refused_with_advice_and_nothing_is_stored(tmp_path, sentence, message):
    routes, store = rig(tmp_path, recurring_cards())
    key = routes.verdict_candidates(REQUEST)["candidates"][0]["key"]

    with pytest.raises(BadRequestError, match=message) as refused:
        routes.save_verdicts({"project": PROJECT, "verdicts": [{"key": key, "sentence": sentence}]})

    assert "resend" in str(refused.value) and store.review.verdicts.sentences(PROJECT) == {}


def test_an_unknown_key_is_refused_naming_it_and_saves_none_of_the_batch(tmp_path):
    routes, store = rig(tmp_path, recurring_cards())
    key = routes.verdict_candidates(REQUEST)["candidates"][0]["key"]
    items = [{"key": key, "sentence": WORTH}, {"key": "failure:nope", "sentence": WORTH}]

    with pytest.raises(BadRequestError, match="no group failure:nope"):
        routes.save_verdicts({"project": PROJECT, "verdicts": items})

    assert store.review.verdicts.sentences(PROJECT) == {}


def test_dataset_history_is_refused_like_session_candidates(tmp_path):
    routes, _ = rig(tmp_path, recurring_cards(), extra_sources=["swe-chat"])

    with pytest.raises(BadRequestError, match="swe-chat dataset history is not shown"):
        routes.verdict_candidates(REQUEST)


def test_a_sentence_outlives_a_remine_and_a_credential_in_it_is_scrubbed(tmp_path):
    routes, store = rig(tmp_path, recurring_cards())
    key = routes.verdict_candidates(REQUEST)["candidates"][0]["key"]
    secret = "ghp_" + "a1B2c3D4e5F6g7H8i9J0" * 2
    sentence = f"Worth a look: the token {secret} was pasted into the command."
    routes.save_verdicts({"project": PROJECT, "verdicts": [{"key": key, "sentence": sentence}]})

    store.mined.save(
        PROJECT, [], MiningOutcome([], incidents=recurring_cards()), held_out_tasks=frozenset()
    )

    kept = store.review.verdicts.sentences(PROJECT)[key]
    assert secret not in kept and kept.startswith("Worth a look: ")

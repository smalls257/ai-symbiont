"""Own-history consent: explicit, default withheld; third-party data never reaches Spark."""

from dataclasses import replace

import pytest

from record_builders import PUBLIC, edit, run, session, user
from symbiont.delivery.hooks import DATASET_PREFIX
from symbiont.miner.lessons import spark_allowed
from symbiont.records.privacy import LIVE_DATASET_PREFIX, OwnHistoryConsent, is_own_history
from symbiont.records.schema import Provenance, dump_jsonl, load_jsonl
from symbiont.store.consent import ConsentFileError, read_consent, record_consent
from symbiont.store.local import ForgetMismatchError, Source, SparkPrivacyViolationError, Store
from symbiont.store.mining import MiningRules, remine
from symbiont.store.training import lessons_for_memory_model

pytestmark = pytest.mark.periphery

PROJECT = "demo"
READER = "records-jsonl"
OWN = Provenance(dataset="private-sessions", license="none", spark_safe=False)
LIVE = Provenance(dataset="live-claude_code", license="local-session", spark_safe=False)
SWE_CHAT = Provenance(dataset="swe-chat", license="see-dataset-card", spark_safe=False)
GIVEN, WITHHELD = OwnHistoryConsent.GIVEN, OwnHistoryConsent.WITHHELD
# Built by concatenation so no credential-shaped literal sits in the repo.
TOKEN = "gh" + "p_" + "A1b2C3d4" * 5


def read_records_jsonl(path, project):
    with path.open(encoding="utf-8") as fh:
        return iter(list(load_jsonl(fh)))


def failing(session_id, provenance, command="pytest tests/test_cart.py"):
    records = session(user("fix it"), run(command, 1, "ImportError: x"), edit("cart.py"))
    return [
        replace(r, project=PROJECT, session_id=session_id, provenance=provenance) for r in records
    ]


def store_with(tmp_path, *sessions):
    store = Store.open(tmp_path / "store.db")
    sources = []
    for i, records in enumerate(sessions):
        path = tmp_path / f"log{i}.jsonl"
        with path.open("w") as fh:
            dump_jsonl(records, fh)
        sources.append(Source(PROJECT, READER, str(path)))
    remine(store, PROJECT, MiningRules({READER: read_records_jsonl}, frozenset()), adding=sources)
    return store


def test_hooks_label_live_records_as_the_users_own():
    assert DATASET_PREFIX == LIVE_DATASET_PREFIX
    assert is_own_history("live-claude_code") and is_own_history("private-sessions")
    assert not is_own_history("swe-chat") and not is_own_history("mini-swe-agent-unlabeled")


def test_consent_off_refuses_own_lessons_for_spark(tmp_path):
    store = store_with(tmp_path, failing("mine", OWN))
    with pytest.raises(SparkPrivacyViolationError):
        lessons_for_memory_model(store, PROJECT, WITHHELD)
    with pytest.raises(SparkPrivacyViolationError):
        store.spark_view().lessons(PROJECT)


def test_consent_on_allows_own_and_live_lessons(tmp_path):
    store = store_with(tmp_path, failing("mine", OWN), failing("live", LIVE), failing("p", PUBLIC))
    assert len(lessons_for_memory_model(store, PROJECT, GIVEN)) == 3


def test_a_third_party_lesson_is_refused_even_with_consent(tmp_path):
    store = store_with(tmp_path, failing("mine", OWN), failing("chat", SWE_CHAT))
    with pytest.raises(SparkPrivacyViolationError):
        lessons_for_memory_model(store, PROJECT, GIVEN)
    with pytest.raises(SparkPrivacyViolationError):
        store.spark_view(GIVEN).lessons(PROJECT)


def test_a_private_lesson_naming_no_dataset_stays_blocked(tmp_path):
    store = store_with(tmp_path, failing("mine", OWN))
    (lesson,) = store.lessons(PROJECT)
    assert lesson.private_datasets == ("private-sessions",)
    assert not spark_allowed(replace(lesson, private_datasets=()), GIVEN)


def test_spark_bound_lessons_are_scrubbed_of_credentials(tmp_path):
    command = f"curl -H 'Authorization: token {TOKEN}' https://example.com"
    store = store_with(tmp_path, failing("mine", OWN, command=command))
    (lesson,) = store.spark_view(GIVEN).lessons(PROJECT)
    text = " ".join([lesson.quote, *lesson.pain_point.signature.key, *lesson.resolution])
    assert TOKEN not in text
    assert TOKEN in " ".join(
        store.lessons(PROJECT)[0].pain_point.signature.key + (store.lessons(PROJECT)[0].quote,)
    )


def test_consent_file_defaults_to_withheld_and_refuses_garbage(tmp_path):
    assert read_consent(tmp_path) is WITHHELD
    record_consent(tmp_path, GIVEN)
    assert read_consent(tmp_path) is GIVEN
    (tmp_path / "consent.json").write_text("{}")
    with pytest.raises(ConsentFileError):
        read_consent(tmp_path)


def test_forgetting_a_scrubbed_export_deletes_the_raw_row(tmp_path):
    command = f"curl -H 'Authorization: token {TOKEN}' https://example.com"
    store = store_with(tmp_path, failing("mine", OWN, command=command))
    exported = lessons_for_memory_model(store, PROJECT, GIVEN)
    assert TOKEN not in exported[0].quote
    assert store.forget_trained(PROJECT, tmp_path / "m.json", exported=exported) == 1
    assert store.lessons(PROJECT) == []


def test_forgetting_lessons_the_store_does_not_hold_raises_and_deletes_nothing(tmp_path):
    store = store_with(tmp_path, failing("mine", OWN))
    (lesson,) = store.lessons(PROJECT)
    stranger = replace(lesson, pain_point=replace(lesson.pain_point, step=99))
    with pytest.raises(ForgetMismatchError, match="nothing was forgotten"):
        store.forget_trained(PROJECT, tmp_path / "m.json", exported=[lesson, stranger])
    assert len(store.lessons(PROJECT)) == 1
    assert not (tmp_path / "m.json").exists()

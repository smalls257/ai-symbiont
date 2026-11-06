"""The session's model curates lessons through service routes; symbiont calls no model.

Failures guarded against: storing for a repository nobody allowed, showing one harness's history
to another's session model, and a verdict that does not change what the note says.
"""

import pytest

from record_builders import edit, run, session, user
from symbiont.miner.lesson_context import LessonContext, Priority
from symbiont.miner.lessons import lessons_from
from symbiont.miner.mine import mine_history, sessions_of
from symbiont.miner.trained import lesson_id
from symbiont.records.schema import dump_jsonl, load_jsonl
from symbiont.service.curation_routes import CurationRoutes
from symbiont.service.effective_context import effective_contexts
from symbiont.service.request_shapes import BadRequestError
from symbiont.store.local import Source, Store
from symbiont.store.repos import RepoRegistry, RepoStance
from symbiont.store.settings import CorrectionSettings

pytestmark = pytest.mark.periphery
PROJECT = "demo"


def read_jsonl(path, project):
    with path.open(encoding="utf-8") as fh:
        return iter(list(load_jsonl(fh)))


def mined_records():
    from dataclasses import replace

    steps = session(
        user("add refunds"),
        edit("src/billing/refund.py"),
        user("No, don't touch refund.py, use the ledger instead"),
        run("pytest tests/test_refund.py", 1, 'File "src/billing/refund.py"\nE   assert 1 == 2'),
        edit("src/billing/refund.py", diff="-a\n+b\n"),
        run("pytest tests/test_refund.py", 0, "1 passed"),
    )
    return [replace(step, project=PROJECT, session_id="s1") for step in steps]


def rig(tmp_path, harness="muse-code", settings=None, *, allow=True):
    records = mined_records()
    log = tmp_path / "log.jsonl"
    with log.open("w") as fh:
        dump_jsonl(records, fh)
    store = Store.open(tmp_path / "s.db")
    lessons = lessons_from(mine_history(sessions_of(records), {}), records)
    store.save_mining(
        PROJECT, [Source(PROJECT, harness, str(log))], lessons, held_out_tasks=frozenset()
    )
    registry = RepoRegistry(tmp_path)
    if allow:
        registry.record_stance(PROJECT, RepoStance.GIVEN)
    routes = CurationRoutes(
        store, registry, lambda: settings or CorrectionSettings(), {harness: read_jsonl}
    )
    return routes, store, lessons


def test_nothing_is_stored_for_a_repository_nobody_allowed(tmp_path):
    routes, store, _ = rig(tmp_path, allow=False)

    with pytest.raises(BadRequestError, match="repo allow"):
        routes.add_lessons(
            {"project": PROJECT, "lessons": [{"text_in_plain_words": "x", "kind": "rule"}]}
        )
    assert store.curation.authored(PROJECT) == []


def test_written_lessons_are_validated_and_stored_with_their_tags(tmp_path):
    routes, store, _ = rig(tmp_path)

    result = routes.add_lessons(
        {
            "project": PROJECT,
            "lessons": [
                {
                    "text_in_plain_words": "Ledger writes are append-only.",
                    "kind": "rule",
                    "files": ["src/ledger/entries.py"],
                    "severity": "high",
                    "source_label": "team notes",
                    "applies_to": {"terms": ["ledger", "BHD"], "areas": ["ledger/"]},
                }
            ],
        }
    )

    (kept,) = store.curation.authored(PROJECT)
    assert (
        result["added"] == 1
        and kept.applies.areas == ("ledger/",)
        and kept.severity.value == "high"
    )
    for bad in ({"kind": "opinion"}, {"severity": "urgent"}, {"files": "a.py"}):
        item = {"text_in_plain_words": "x", "kind": "rule", **bad}
        with pytest.raises(BadRequestError):
            routes.add_lessons({"project": PROJECT, "lessons": [item]})


def test_correction_candidates_come_from_same_harness_history_trimmed_and_capped(tmp_path):
    routes, _, _ = rig(tmp_path)

    result = routes.correction_candidates({"project": PROJECT, "running_in": "muse_code"})

    (candidate,) = result["candidates"]
    assert candidate["candidate_id"] == "s1:2" and "don't touch" in candidate["excerpt"]
    assert candidate["after"] == "edited `src/billing/refund.py`"
    assert result["not_shown"] == []


def test_another_harness_history_is_withheld_unless_cross_harness_is_switched_on(tmp_path):
    routes, _, _ = rig(tmp_path)

    held = routes.correction_candidates({"project": PROJECT, "running_in": "claude_code"})

    assert held["candidates"] == [] and "muse_code history is not shown" in held["not_shown"][0]
    other = tmp_path / "again"
    other.mkdir()
    routes2, _, _ = rig(other, settings=CorrectionSettings(cross_harness=True))
    assert routes2.correction_candidates({"project": PROJECT, "running_in": "claude_code"})[
        "candidates"
    ]


def test_the_muse_switch_turns_muse_correction_finding_off(tmp_path):
    routes, _, _ = rig(
        tmp_path, settings=CorrectionSettings(enabled={"claude_code": True, "muse_code": False})
    )

    result = routes.correction_candidates({"project": PROJECT, "running_in": "muse_code"})

    assert result["candidates"] == [] and result["not_shown"]


def test_saved_corrections_become_lessons_and_are_not_offered_again(tmp_path):
    routes, store, _ = rig(tmp_path)
    saved = routes.save_corrections(
        {
            "project": PROJECT,
            "corrections": [
                {
                    "candidate_id": "s1:2",
                    "is_correction": True,
                    "rule_in_plain_words": "Use the ledger, not refund.py.",
                }
            ],
        }
    )

    again = routes.correction_candidates({"project": PROJECT, "running_in": "muse_code"})

    assert saved == {"judged": 1, "lessons_added": 1}
    assert store.curation.authored(PROJECT)[0].kind.value == "correction"
    assert again["candidates"] == []
    with pytest.raises(BadRequestError, match="no rule_in_plain_words"):
        routes.save_corrections(
            {"project": PROJECT, "corrections": [{"candidate_id": "s1:9", "is_correction": True}]}
        )


def test_review_candidates_are_capped_and_verdicts_change_what_the_note_says(tmp_path):
    routes, store, lessons = rig(tmp_path)
    ident = lesson_id(lessons[0])

    batch = routes.review_candidates({"project": PROJECT})
    routes.save_reviews(
        {
            "project": PROJECT,
            "reviews": [
                {
                    "id": ident,
                    "verdict": "mistake",
                    "rule_in_plain_words": "Refunds go through the ledger.",
                    "title": "Refund edits",
                    "applies_to": {"terms": ["refund"]},
                }
            ],
        }
    )
    merged = effective_contexts(store, PROJECT)[ident]

    assert batch["candidates"][0]["id"] == ident and "context" in batch["candidates"][0]
    assert merged.text == "Refunds go through the ledger" and not merged.intentional
    assert merged.applies.terms == ("refund",)
    assert routes.review_candidates({"project": PROJECT})["candidates"] == []


def test_expected_and_noise_silence_but_the_developers_own_context_overrides(tmp_path):
    routes, store, lessons = rig(tmp_path)
    ident = lesson_id(lessons[0])
    routes.save_reviews({"project": PROJECT, "reviews": [{"id": ident, "verdict": "noise"}]})
    assert effective_contexts(store, PROJECT)[ident].intentional

    store.contexts.save(ident, PROJECT, LessonContext("This one matters.", False, Priority.HIGH))

    kept = effective_contexts(store, PROJECT)[ident]
    assert not kept.intentional and kept.text == "This one matters"


def test_a_review_for_an_unknown_pain_point_is_refused(tmp_path):
    routes, _, _ = rig(tmp_path)

    with pytest.raises(BadRequestError, match="no pain point"):
        routes.save_reviews({"project": PROJECT, "reviews": [{"id": "x:1:y", "verdict": "noise"}]})


def test_the_focus_answer_is_remembered(tmp_path):
    routes, _, _ = rig(tmp_path)

    routes.set_focus(
        {"project": PROJECT, "text": "money rules", "keywords": ["money"], "sources": ["notes.md"]}
    )

    assert RepoRegistry(tmp_path).focus(PROJECT)["keywords"] == ["money"]


def test_a_lesson_without_areas_gets_its_files_module_directories_and_written_areas_are_kept(
    tmp_path,
):
    routes, store, _ = rig(tmp_path)
    base = {"kind": "rule", "files": ["pkg/arr/a.py", "src/b.py", "c.py"]}

    routes.add_lessons(
        {
            "project": PROJECT,
            "lessons": [
                {**base, "text_in_plain_words": "No areas given."},
                {**base, "text_in_plain_words": "Areas given.", "applies_to": {"areas": ["x/"]}},
            ],
        }
    )

    derived, kept = store.curation.authored(PROJECT)
    assert derived.applies.areas == ("pkg/arr",) and kept.applies.areas == ("x/",)


def test_text_and_rule_are_accepted_as_the_lesson_words(tmp_path):
    routes, store, _ = rig(tmp_path)

    result = routes.add_lessons(
        {
            "project": PROJECT,
            "lessons": [
                {"text": "Totals round once.", "kind": "rule"},
                {"rule": "Ledger is append-only.", "kind": "rule"},
            ],
        }
    )

    kept = {lesson.text for lesson in store.curation.authored(PROJECT)}
    assert result["added"] == 2 and kept == {"Totals round once.", "Ledger is append-only."}


def test_a_bad_lesson_error_names_the_fields_and_asks_for_the_same_content_again(tmp_path):
    routes, _, _ = rig(tmp_path)

    with pytest.raises(BadRequestError) as caught:
        routes.add_lessons({"project": PROJECT, "lessons": [{"words": "x", "kind": "rule"}]})

    message = str(caught.value)
    assert "text_in_plain_words" in message and "kind" in message and "SAME" in message


def test_a_review_summary_is_saved_and_one_longer_than_the_cap_is_cut_not_refused(tmp_path):
    from symbiont.service.curation_routes import MAX_TEXT

    routes, store, lessons = rig(tmp_path)
    ident = lesson_id(lessons[0])

    routes.save_reviews(
        {
            "project": PROJECT,
            "reviews": [{"id": ident, "verdict": "mistake", "summary": "  " + "s" * 5000}],
        }
    )

    assert store.curation.reviews(PROJECT)[ident].summary == "s" * MAX_TEXT


def test_the_review_candidate_route_offers_the_asked_turn(tmp_path):
    routes, _store, _lessons = rig(tmp_path)

    (candidate,) = routes.review_candidates({"project": PROJECT})["candidates"]

    assert "asked" in candidate and "outcome" in candidate

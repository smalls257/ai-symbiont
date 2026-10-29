"""The Spark author and judge on a fake transport: strict parsing, honest labels, no network."""

import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "evolve"))

import spark_author  # noqa: E402 - needs the scripts path added above
import spark_judge  # noqa: E402

from symbiont.act1.card_genome import Card, CardCapError, Lesson  # noqa: E402
from symbiont.act1.generality import Rejection  # noqa: E402
from symbiont.act1.generation import MutationReplyError  # noqa: E402
from symbiont.act1.lineage import Operator  # noqa: E402
from symbiont.egress.credentials import ApiKey  # noqa: E402
from symbiont.egress.spark import Effort, SparkSession  # noqa: E402
from symbiont.egress.spend import Ledger, SpendCaps, Tier  # noqa: E402
from symbiont.records.schema import Provenance  # noqa: E402

pytestmark = pytest.mark.periphery
SAFE = Provenance(dataset="act1-freedoom2-selfplay", license="BSD-3-Clause", spark_safe=True)
PRIVATE = Provenance(dataset="owner-sessions", license="private", spark_safe=False)
PARENT = Card.of(
    [Lesson("Fired at nothing", "Shoot only at a visible enemy", "Is an enemy in view?")]
)
GOOD = (
    "LESSON: Walked into a wall || Use go_to so the route goes around || "
    "Did the walk end at a wall?"
)


class FakeTransport:
    def __init__(self, text):
        self.text, self.requests = text, []

    def __call__(self, request, timeout_s):
        self.requests.append(json.loads(request.data))
        body = {
            "choices": [{"message": {"content": self.text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 400, "completion_tokens": 50},
        }
        return json.dumps(body).encode()


def session(tmp_path, text, provenance=(SAFE,)):
    return SparkSession(
        "muse-spark-1.3-contributor", Tier.CONTRIBUTOR, "evolve-test", SpendCaps(15.0, 3.0),
        ApiKey("test-token"), Ledger(tmp_path / "ledger.jsonl"), provenance, FakeTransport(text),
    )  # fmt: skip


def test_a_well_formed_reply_becomes_the_expected_card(tmp_path):
    author = spark_author.SparkAuthor(
        session(tmp_path, GOOD + "\n" + GOOD.replace("wall", "ledge")), Effort.MEDIUM
    )
    card = author.vary(Operator.ADD, (PARENT,), "In 2 of 4 games the exit was not reached.", 7)
    assert len(card.lessons) == 2
    assert card.lessons[0] == Lesson(
        "Walked into a wall", "Use go_to so the route goes around", "Did the walk end at a wall?"
    )


def test_the_prompt_holds_the_task_the_card_and_the_summary_and_the_effort_is_medium(tmp_path):
    spark = session(tmp_path, GOOD)
    spark_author.SparkAuthor(spark, Effort.MEDIUM).vary(Operator.REWRITE, (PARENT,), "SUMMARY X", 1)
    sent = spark.transport.requests[0]
    prompt = sent["messages"][0]["content"]
    assert "Rewrite one lesson" in prompt and "Shoot only at a visible enemy" in prompt
    assert "SUMMARY X" in prompt and sent["reasoning_effort"] == "medium"


def test_nine_lessons_raise_the_card_cap_error(tmp_path):
    nine = "\n".join(f"LESSON: wrong {i} || instead {i} || check {i}" for i in range(9))
    with pytest.raises(CardCapError):
        spark_author.SparkAuthor(session(tmp_path, nine), Effort.MEDIUM).vary(
            Operator.ADD, (PARENT,), "s", 1
        )


@pytest.mark.parametrize(
    "reply",
    [
        "Here is the card: ...",
        "LESSON: only one part",
        "LESSON: a || b ||",
        "",
        "1. wrong || x || y",
    ],
)
def test_free_text_and_malformed_lines_raise_the_reply_error(tmp_path, reply):
    with pytest.raises(MutationReplyError):
        spark_author.SparkAuthor(session(tmp_path, reply), Effort.MEDIUM).vary(
            Operator.ADD, (PARENT,), "s", 1
        )


def test_the_empty_card_reply_is_an_empty_card(tmp_path):
    card = spark_author.SparkAuthor(session(tmp_path, "EMPTY CARD"), Effort.MEDIUM).vary(
        Operator.DELETE, (PARENT,), "s", 1
    )
    assert card.lessons == ()


def test_the_judge_maps_landmark_to_the_landmark_rejection_and_general_to_general(tmp_path):
    lesson = PARENT.lessons[0]
    landmark = spark_judge.SparkJudge(
        session(tmp_path, "LANDMARK: names a room by its key"), Effort.MEDIUM
    )
    verdict = landmark.landmark(lesson)
    assert not verdict.general and verdict.rejection is Rejection.LANDMARK
    assert verdict.evidence == "names a room by its key"
    assert (
        spark_judge.SparkJudge(session(tmp_path, "GENERAL"), Effort.MEDIUM).landmark(lesson).general
    )


@pytest.mark.parametrize("reply", ["Probably general.", "general", "GENERALLY fine", ""])
def test_any_other_judge_reply_raises(tmp_path, reply):
    with pytest.raises(spark_judge.JudgeReplyError):
        spark_judge.SparkJudge(session(tmp_path, reply), Effort.MEDIUM).landmark(PARENT.lessons[0])


def test_calls_are_labeled_in_the_ledger_and_declare_spark_safe_provenance(tmp_path):
    spark = session(tmp_path, GOOD)
    spark_author.SparkAuthor(spark, Effort.MEDIUM).vary(Operator.ADD, (PARENT,), "s", 1)
    labels = [row["label"] for row in spark.ledger.entries()]
    assert labels == [f"evolve/evolve-test/author/{PARENT.card_id}"]
    assert all(p.spark_safe for p in spark.provenance)


def test_a_private_provenance_is_refused_before_anything_is_sent(tmp_path):
    spark = session(tmp_path, GOOD, provenance=(PRIVATE,))
    with pytest.raises(Exception, match="spark_safe|refus|private"):
        spark_author.SparkAuthor(spark, Effort.MEDIUM).vary(Operator.ADD, (PARENT,), "s", 1)
    assert spark.transport.requests == []


def test_no_log_line_holds_the_prompt_text(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    spark = session(tmp_path, GOOD)
    spark_author.SparkAuthor(spark, Effort.MEDIUM).vary(
        Operator.ADD, (PARENT,), "UNIQUE-SUMMARY", 1
    )
    assert (
        "UNIQUE-SUMMARY" not in caplog.text and "Shoot only at a visible enemy" not in caplog.text
    )


def test_a_reason_after_general_is_accepted_and_a_bare_landmark_is_a_landmark(tmp_path):
    lesson = PARENT.lessons[0]
    general = spark_judge.SparkJudge(
        session(tmp_path, "GENERAL: a habit that works anywhere"), Effort.MEDIUM
    )
    assert general.landmark(lesson).general
    bare = spark_judge.SparkJudge(session(tmp_path, "LANDMARK"), Effort.MEDIUM).landmark(lesson)
    assert not bare.general and bare.evidence == "no reason given"


def test_author_and_judge_ask_for_room_to_think_and_answer(tmp_path):
    spark = session(tmp_path, GOOD)
    spark_author.SparkAuthor(spark, Effort.MEDIUM).vary(Operator.ADD, (PARENT,), "s", 1)
    spark_judge.SparkJudge(session(tmp_path, "GENERAL"), Effort.MEDIUM).landmark(PARENT.lessons[0])
    assert spark.transport.requests[0]["max_tokens"] == spark_author.REPLY_TOKENS >= 16384
    assert spark_judge.REPLY_TOKENS >= 16384


def test_the_compare_operator_puts_the_best_and_worst_game_texts_in_the_prompt(tmp_path):
    spark = session(tmp_path, GOOD)
    spark_author.SparkAuthor(spark, Effort.MEDIUM).vary(
        Operator.COMPARE, (PARENT,), "BEST GAME: reached the exit. WORST GAME: stood still.", 1
    )
    prompt = spark.transport.requests[0]["messages"][0]["content"]
    assert "Compare the best game with the worst game" in prompt
    assert "BEST GAME: reached the exit." in prompt and "WORST GAME: stood still." in prompt

"""Route B training rows and held-out checks, on a hand-written lesson."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


@pytest.fixture(autouse=True)
def forget_loaded_modules():
    """Drop the modules a test imported so one test's modules never reach another."""
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        del sys.modules[name]


def load(monkeypatch, folder, name):
    monkeypatch.syspath_prepend(str(SCRIPTS / "routea"))
    monkeypatch.syspath_prepend(str(SCRIPTS / "routeb"))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / folder / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def a_lesson(monkeypatch):
    lessons = load(monkeypatch, "routea", "lessons")
    return lessons.Lesson(
        lesson_id="abc123def456",
        repo="org/repo",
        program="pytest",
        file="tests/test_a.py",
        failed="pytest tests/test_a.py",
        error="ModuleNotFoundError: No module named 'pkg'",
        error_class="ModuleNotFoundError",
        fix="PYTHONPATH=src pytest tests/test_a.py",
        added=("PYTHONPATH=src",),
    )


def test_card_names_what_happened_the_fix_and_the_check(monkeypatch):
    cards = load(monkeypatch, "routeb", "cards")
    text = cards.card(a_lesson(monkeypatch))
    assert text.startswith("What happened: in org/repo, `pytest tests/test_a.py` failed with")
    assert "How it was resolved: `PYTHONPATH=src pytest tests/test_a.py` exited 0." in text
    assert "The check to run: before running pytest on tests/test_a.py" in text
    assert "\n" not in text


def test_a_card_passes_the_lcap_note_scorer(monkeypatch):
    lesson = a_lesson(monkeypatch)
    cards = load(monkeypatch, "routeb", "cards")
    scoring = load(monkeypatch, "routea", "scoring")
    questions = load(monkeypatch, "routea", "questions")
    assert scoring.recalled(cards.card(lesson), lesson, questions.Asks.NOTE)


def test_eight_rows_per_lesson_all_under_glimmers_system_turn(monkeypatch):
    cards = load(monkeypatch, "routeb", "cards")
    rows = cards.training_rows(a_lesson(monkeypatch))
    assert len(rows) == 8
    for row in rows:
        roles = [message["role"] for message in row["messages"]]
        assert roles == ["system", "user", "assistant"]
        assert row["messages"][0]["content"] == cards.SYSTEM
    assert "Reasoning strength: low." in cards.SYSTEM


def test_no_held_out_question_is_a_training_prompt(monkeypatch):
    lesson = a_lesson(monkeypatch)
    cards = load(monkeypatch, "routeb", "cards")
    questions = load(monkeypatch, "routea", "questions")
    prompts = {row["messages"][1]["content"] for row in cards.training_rows(lesson)}
    assert prompts.isdisjoint(q.text for q in questions.held_out_questions(lesson))


def test_ceiling_system_holds_every_lesson_and_the_reasoning_line(monkeypatch):
    lesson = a_lesson(monkeypatch)
    cards = load(monkeypatch, "routeb", "cards")
    system = cards.ceiling_system([lesson])
    assert lesson.text() in system
    assert system.endswith("Reasoning strength: low.")


def _paraphrase_case(monkeypatch):
    lesson = a_lesson(monkeypatch)
    build = load(monkeypatch, "routeb", "build_sets")
    question = {
        "question_id": "abc123def456-1",
        "lesson_id": lesson.lesson_id,
        "asks": "fix",
        "text": "org/repo: which command should replace `pytest tests/test_a.py`?",
    }
    return build, lesson, question


def test_a_paraphrase_that_keeps_repo_and_command_is_kept(monkeypatch):
    build, lesson, question = _paraphrase_case(monkeypatch)
    para = {
        **question,
        "question_id": "abc123def456-1p",
        "text": "In org/repo, what replaces `pytest tests/test_a.py`?",
    }
    assert build.checked_paraphrases([para], [question], [lesson]) == [para]


def test_a_paraphrase_without_its_question_stops_the_build(monkeypatch):
    build, lesson, question = _paraphrase_case(monkeypatch)
    stray = {**question, "question_id": "ffffffffffff-1p", "text": "org/repo `pytest x`?"}
    with pytest.raises(ValueError, match="has no question in this build"):
        build.checked_paraphrases([stray], [question], [lesson])


def test_a_paraphrase_that_drops_the_command_stops_the_build(monkeypatch):
    build, lesson, question = _paraphrase_case(monkeypatch)
    vague = {**question, "question_id": "abc123def456-1p", "text": "org/repo: what do I run?"}
    with pytest.raises(ValueError, match="drops its repo or command"):
        build.checked_paraphrases([vague], [question], [lesson])


def test_lcap_budget_gives_the_lcap_step_counts(monkeypatch):
    schedule = load(monkeypatch, "routeb", "lora_schedule")
    budget = schedule.Budget()
    assert [budget.steps(rows) for rows in (80, 240, 800)] == [160, 480, 1600]
    with pytest.raises(ValueError, match="not more than the warmup"):
        budget.steps(10)


def test_learning_rate_warms_up_then_decays_to_the_floor(monkeypatch):
    schedule = load(monkeypatch, "routeb", "lora_schedule")
    budget = schedule.Budget()
    rates = [schedule.lr_at(step, 160, budget) for step in range(161)]
    assert rates[0] == budget.floor_lr
    assert rates[budget.warmup] == pytest.approx(budget.peak_lr)
    assert max(rates) == pytest.approx(budget.peak_lr)
    assert rates[160] == pytest.approx(budget.floor_lr)
    assert all(
        a >= b for a, b in zip(rates[budget.warmup : -1], rates[budget.warmup + 1 :], strict=True)
    )


def test_every_row_is_seen_once_per_epoch_in_a_seeded_order(monkeypatch):
    schedule = load(monkeypatch, "routeb", "lora_schedule")
    budget = schedule.Budget()
    plan = schedule.batch_order(80, budget, seed=0)
    assert len(plan) == 160 and all(len(step) == 4 for step in plan)
    first_epoch = [row for step in plan[:20] for row in step]
    assert sorted(first_epoch) == list(range(80))
    assert plan == schedule.batch_order(80, budget, seed=0)
    assert plan != schedule.batch_order(80, budget, seed=1)


def test_only_answer_tokens_carry_loss_and_padding_is_masked(monkeypatch):
    schedule = load(monkeypatch, "routeb", "lora_schedule")
    ids, labels = schedule.masked([1, 2, 3], [7, 8])
    assert ids == [1, 2, 3, 7, 8]
    assert labels == [-100, -100, -100, 7, 8]
    with pytest.raises(ValueError, match="answer token"):
        schedule.masked([1], [])
    batch_ids, batch_labels, mask = schedule.padded([(ids, labels), ([5, 6], [-100, 6])], pad_id=0)
    assert batch_ids[1] == [5, 6, 0, 0, 0]
    assert batch_labels[1] == [-100, 6, -100, -100, -100]
    assert mask == [[1, 1, 1, 1, 1], [1, 1, 0, 0, 0]]


class FakeTemplate:
    """A chat template shaped like Glimmer's: <s>, role headers, answers end with <|eot|>."""

    def __init__(self, answer_suffix="<|eot|>"):
        self.answer_suffix = answer_suffix

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=False):
        text = "<s>" + "".join(
            f"<|start|>{m['role']}<|message|>{m['content']}<|eot|>"
            for m in messages
            if m["role"] != "assistant"
        )
        for m in messages:
            if m["role"] == "assistant":
                text += f"<|start|>assistant to=user<|message|>{m['content']}{self.answer_suffix}"
        return text + ("<|start|>assistant" if add_generation_prompt else "")

    def __call__(self, text, add_special_tokens=False):
        class Encoded:
            input_ids = [ord(char) for char in text]

        return Encoded()


def _row():
    return {
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "answer"},
        ]
    }


def test_a_row_splits_at_the_user_channel(monkeypatch):
    chat = load(monkeypatch, "routeb", "glimmer_chat")
    prompt, answer = chat.row_ids(FakeTemplate(), _row())
    assert "".join(map(chr, answer)) == "answer<|eot|>"
    assert "".join(map(chr, prompt)).endswith("<|start|>assistant to=user<|message|>")


def test_a_template_that_renders_differently_stops_training(monkeypatch):
    chat = load(monkeypatch, "routeb", "glimmer_chat")
    with pytest.raises(chat.TemplateSplitError, match="prompt \\+ answer"):
        chat.row_ids(FakeTemplate(answer_suffix="<|eom|>"), _row())


def test_the_answerer_applies_only_the_chosen_adapter(monkeypatch):
    monkeypatch.setitem(sys.modules, "transformers", type(sys)("transformers"))
    sys.modules["transformers"].AutoTokenizer = object
    answer = load(monkeypatch, "routeb", "answer_glimmer")
    assert answer.lora_scales(3, None) == [0.0, 0.0, 0.0]
    assert answer.lora_scales(3, 2) == [0.0, 0.0, 1.0]
    with pytest.raises(ValueError, match="not among"):
        answer.lora_scales(3, 3)

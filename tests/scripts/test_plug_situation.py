"""Plug situation items and scoring on hand-written lessons."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROUTEA = Path(__file__).resolve().parents[2] / "scripts" / "routea"
SCRIPT_DIRS = {ROUTEA, ROUTEA.parent / "aidev"}


@pytest.fixture(autouse=True)
def forget_script_modules():
    """Drop only modules loaded from scripts/; shared libraries stay loaded."""
    yield
    for name, module in list(sys.modules.items()):
        if Path(getattr(module, "__file__", None) or "/").parent in SCRIPT_DIRS:
            del sys.modules[name]


@pytest.fixture
def sit(monkeypatch):
    monkeypatch.syspath_prepend(str(ROUTEA))
    spec = importlib.util.spec_from_file_location("plug_situation", ROUTEA / "plug_situation.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["plug_situation"] = module
    spec.loader.exec_module(module)
    return module


def lesson(sit, repo, number, error="TypeError"):
    return sit.Lesson(
        lesson_id=f"{repo}-{number}",
        repo=repo,
        program="pytest",
        file=f"tests/test_{number}.py",
        failed=f"pytest tests/test_{number}.py",
        error=f"{error}: boom {number}",
        error_class=error,
        fix=f"pytest tests/test_{number}.py --opt{number}",
        added=(f"--opt{number}",),
    )


def pool(sit, size=80):
    return [lesson(sit, f"org/other{n % 7}", 100 + n, error="KeyError") for n in range(size)]


def fixed(sit, repo, number, fix, added, error="TypeError"):
    """A lesson with a chosen fix command and fix tokens."""
    return sit.Lesson(
        lesson_id=f"{repo}-{number}",
        repo=repo,
        program="tox",
        file=f"src/m{number}.py",
        failed="tox",
        error=f"{error}: boom",
        error_class=error,
        fix=fix,
        added=added,
    )


def test_each_lesson_gives_a_pick_item_and_a_silence_item_without_it(sit):
    lessons = [lesson(sit, "org/r", n) for n in range(5)]
    items = sit.build_items({"org/r": lessons}, pool(sit))
    assert len(items) == 10
    for pick, quiet in zip(items[::2], items[1::2], strict=True):
        assert pick.item_id.endswith("-pick") and quiet.item_id.endswith("-silence")
        assert pick.applies in pick.prompt_lessons and quiet.applies is None
        assert quiet.prompt_lessons == tuple(
            o for o in pick.prompt_lessons if o is not pick.applies
        )
        assert len(pick.prompt_lessons) == sit.PROMPT_LESSONS


def test_no_distractor_shares_the_lessons_failure_key(sit):
    right = fixed(sit, "org/r", 1, "tox -e py", ("-e", "py"))
    twin = fixed(sit, "org/x", 2, "tox -e py", ("-e", "py"))
    items = sit.build_items({"org/r": [right]}, [twin, *pool(sit)])
    assert all(twin not in item.prompt_lessons for item in items)


def test_too_few_lessons_to_fill_the_prompt_raises(sit):
    with pytest.raises(ValueError, match="cannot fill"):
        sit.build_items({"org/r": [lesson(sit, "org/r", 1)]}, pool(sit, size=10))


def test_whole_token_matching_and_a_near_miss(sit):
    right = fixed(sit, "org/r", 1, "pytest --runslow tests", ("--runslow",))
    assert sit.names_fix("Run `pytest --runslow tests`.", right)
    assert sit.names_fix("add --runslow, then rerun", right)
    assert not sit.names_fix("add --runslower", right)  # substring of a token is not the token
    assert not sit.names_fix("pytest --runfast tests", right)  # one token off


def test_a_lesson_named_by_the_right_fix_is_excused_not_a_wrong_pick(sit):
    right = fixed(sit, "org/r", 1, "pytest -x --cov src", ("-x", "--cov"))
    flag = fixed(sit, "org/x", 2, "pytest --cov", ("--cov",))
    other = fixed(sit, "org/y", 3, "pip install foo", ("foo",))
    item = sit.Item("i-pick", "s", (flag, other, right), right, ("org/x-2",))
    assert sit.verdict(item, "TypeError: run pytest -x --cov src")["pick"]
    two = sit.verdict(item, "run pytest -x --cov src or pip install foo")
    assert two["wrong_pick"] and not two["pick"]


def test_build_excuses_lessons_the_right_fix_names(sit):
    right = fixed(sit, "org/r", 1, "pytest -x --cov src", ("-x", "--cov"))
    flag = fixed(sit, "org/x", 2, "pytest --cov", ("--cov",), error="KeyError")
    items = sit.build_items({"org/r": [right]}, [flag, *pool(sit)])
    pick = items[0]
    assert ("org/x-2" in pick.excused) is (flag in pick.prompt_lessons)
    assert items[1].excused == ()


def test_verdicts_pick_useful_wrong_and_silent(sit):
    right, other = lesson(sit, "org/r", 1), lesson(sit, "org/x", 2, error="KeyError")
    pick = sit.Item("i-pick", "s", (right, other), right)
    assert sit.verdict(pick, "TypeError again: add --opt1")["useful"]
    assert sit.verdict(pick, "add --opt1")["pick"] and not sit.verdict(pick, "add --opt1")["useful"]
    assert sit.verdict(pick, "add --opt2")["wrong_pick"]
    quiet = sit.Item("i-silence", "s", (other,), None)
    assert sit.verdict(quiet, "No lesson I hold covers that.")["silent"]
    assert not sit.verdict(quiet, "No lesson applies, but try --opt2")["silent"]


def test_rates_need_both_kinds_and_every_answer(sit):
    right, other = lesson(sit, "org/r", 1), lesson(sit, "org/x", 2)
    items = [sit.Item("a", "s", (right, other), right), sit.Item("b", "s", (other,), None)]
    found = sit.rates(items, {"a": "TypeError: --opt1", "b": "no lesson applies"})
    assert found == {"pick": 1.0, "useful": 1.0, "wrong_pick": 0.0, "silence": 1.0}
    with pytest.raises(KeyError):
        sit.rates(items, {"a": "x"})
    with pytest.raises(ValueError):
        sit.rates(items[:1], {"a": "x"})


def test_narrowed_keeps_the_ranker_top_but_not_its_order(sit):
    right = lesson(sit, "org/r", 1)
    far = [lesson(sit, "org/x", n) for n in range(3, 20)]
    orders = []
    for number in range(12):
        item = sit.Item(f"i{number}-pick", sit.situation_of(right), (*far, right), right)
        top = sit.narrowed(item, 5)
        assert set(top.prompt_lessons) == set(sit.lexical_rank(item)[:5])
        orders.append([o.lesson_id for o in top.prompt_lessons].index(right.lesson_id))
    assert sit.lexical_rank(item)[0] is right
    assert any(position != 0 for position in orders)  # the applicable lesson is not always first
    assert sit.narrowed(item, 5) == sit.narrowed(item, 5)  # seeded


def test_ranker_alone_answers_with_its_top_lesson(sit):
    right = lesson(sit, "org/r", 1)
    far = [lesson(sit, "org/x", n) for n in range(3, 8)]
    item = sit.Item("i-pick", sit.situation_of(right), (*far, right), right)
    assert sit.ranker_answer(item) == right.text()


def test_ranker_recall_and_pick_item_abstention(sit):
    right = lesson(sit, "org/r", 1)
    far = [lesson(sit, "org/x", n) for n in range(3, 8)]
    pick = sit.Item("i-pick", sit.situation_of(right), (*far, right), right)
    quiet = sit.Item("i-silence", sit.situation_of(right), tuple(far), None)
    assert sit.ranker_recall([pick, quiet], depths=(1,)) == {"recall_at_1": 1.0}
    answers = {"i-pick": "No lesson applies.", "i-silence": "No lesson applies."}
    assert sit.pick_item_abstention([pick, quiet], answers) == 1.0


def test_round2_split_takes_the_lowest_name_hashes(monkeypatch, sit):
    spec = importlib.util.spec_from_file_location("plug_round2", ROUTEA / "plug_round2.py")
    r2 = importlib.util.module_from_spec(spec)
    sys.modules["plug_round2"] = r2
    spec.loader.exec_module(r2)
    monkeypatch.setattr(r2, "SCORED_COUNT", 2)
    by_repo = {f"org/r{n}": [lesson(sit, f"org/r{n}", m) for m in range(3)] for n in range(5)}
    by_repo["org/big"] = [lesson(sit, "org/big", m) for m in range(9)]
    split = r2.split_round2(by_repo, used={"org/r0"})
    eligible = sorted((f"org/r{n}" for n in range(1, 5)), key=r2.name_hash)
    assert sorted(split["scored"]) == sorted(eligible[:2])
    assert sorted(split["meta_join"]) == sorted(eligible[2:])
    with pytest.raises(ValueError):
        r2.split_round2(by_repo, used=set(by_repo))


def test_every_pick_items_own_note_scores_as_a_pick(sit):
    right = fixed(sit, "org/r", 1, "pytest -x src", ("-x",))
    # The note quotes the failed command `tox`, which is another lesson's whole fix.
    tox = fixed(sit, "org/x", 2, "tox", ("tox",), error="KeyError")
    items = sit.build_items({"org/r": [right]}, [tox, *pool(sit)])
    assert sit.own_note_misses(items) == 0
    assert sit.verdict(items[0], right.text())["pick"]


def test_build_refuses_an_unpassable_item(monkeypatch, sit):
    spec = importlib.util.spec_from_file_location(
        "plug_situation_cli", ROUTEA / "plug_situation_cli.py"
    )
    cli = importlib.util.module_from_spec(spec)
    sys.modules["plug_situation_cli"] = cli
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli, "own_note_misses", lambda items: 1)
    monkeypatch.setattr(cli, "_jsonl", lambda *a: None)
    with pytest.raises(ValueError, match="own correct note"):
        cli.build(Path("unused"), [], Path("unused"))

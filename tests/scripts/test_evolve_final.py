"""The scored card test's gate and scorer: every promise the prereg makes is checked in code."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "evolve"))

import final_test as ft  # noqa: E402 - needs the scripts path added above
import frozen_cards as fc  # noqa: E402
import score_final as sf  # noqa: E402

from symbiont.act1.game_fitness import Case, GameResult, Grade  # noqa: E402
from symbiont.act1.move_cuts import CutSetting  # noqa: E402
from symbiont.eval.prereg import PreregNotFrozenError  # noqa: E402

pytestmark = pytest.mark.periphery
FORBIDDEN = ("evolved", "self-improving", "learned from its own mistakes", "recursive")


def git(root, *args):
    done = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


def prereg_text(pin, status="**FROZEN 2026-10-29.**"):
    mined, strong = fc.MINED_CARD, fc.STRONG_CARD
    return (
        f"# Pre-registration: test\n\n{status} Code pinned at {pin}.\n\n"
        "Claim tags: [measured] and [hypothesis].\n\n"
        f"Mined card (sha256 `{fc.card_sha256(mined)}`):\n\n```\n{mined.render()}\n```\n\n"
        f"Strong hand-written card (sha256 `{fc.card_sha256(strong)}`):\n\n"
        f"```\n{strong.render()}\n```\n"
    )


def make_repo(
    tmp_path, status="**FROZEN 2026-10-29.**", card_hash_wrong=False, extra_in_freeze=False
):
    root = tmp_path / "repo"
    (root / "scripts" / "evolve").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "prereg").mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    (root / "scripts" / "evolve" / "a.py").write_text("print('a')\n")
    (root / "src" / "b.py").write_text("print('b')\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "code")
    pin = git(root, "rev-parse", "HEAD")
    text = prereg_text(pin, status)
    if card_hash_wrong:
        text = text.replace(fc.card_sha256(fc.MINED_CARD), "0" * 64)
    path = root / "prereg" / "2026-10-29-evolve-card.md"
    path.write_text(text)
    if extra_in_freeze:
        (root / "notes.txt").write_text("x")
        git(root, "add", "notes.txt")
    git(root, "add", str(path))
    git(root, "commit", "-qm", "freeze")
    return root, path, pin


def test_the_check_passes_on_a_clean_frozen_repo_and_reports_what_it_verified(tmp_path):
    root, path, pin = make_repo(tmp_path)
    report = ft.check(path, root)
    assert report.pinned_commit == pin and report.code_commit == git(root, "rev-parse", "HEAD")
    assert report.freeze_commit == git(root, "rev-parse", "HEAD")
    assert report.card_hashes["Mined card"] == fc.card_sha256(fc.MINED_CARD)
    assert len(report.prereg_sha256) == 64


def test_an_unfrozen_prereg_is_refused(tmp_path):
    root, path, _ = make_repo(tmp_path, status="DRAFT, not frozen.")
    with pytest.raises(PreregNotFrozenError):
        ft.check(path, root)


def test_a_card_hash_that_differs_from_the_codes_is_refused(tmp_path):
    root, path, _ = make_repo(tmp_path, card_hash_wrong=True)
    with pytest.raises(ft.ScoredRefusalError, match="Mined card"):
        ft.check(path, root)


def test_code_changed_after_the_freeze_is_refused_even_when_committed(tmp_path):
    root, path, _ = make_repo(tmp_path)
    (root / "scripts" / "evolve" / "a.py").write_text("print('changed')\n")
    git(root, "commit", "-qam", "tweak")
    with pytest.raises(ft.ScoredRefusalError, match="scripts/evolve at HEAD differs"):
        ft.check(path, root)


def test_an_uncommitted_edit_or_an_untracked_file_in_the_code_is_refused(tmp_path):
    root, path, _ = make_repo(tmp_path)
    (root / "src" / "b.py").write_text("print('dirty')\n")
    with pytest.raises(ft.ScoredRefusalError):
        ft.check(path, root)
    git(root, "checkout", "--", "src/b.py")
    (root / "src" / "new.py").write_text("x = 1\n")
    with pytest.raises(ft.ScoredRefusalError, match="uncommitted or untracked"):
        ft.check(path, root)


def test_a_freeze_commit_that_changed_more_than_the_prereg_is_refused(tmp_path):
    root, path, _ = make_repo(tmp_path, extra_in_freeze=True)
    with pytest.raises(ft.ScoredRefusalError, match="changed more than"):
        ft.check(path, root)


def test_a_pin_that_is_not_the_freeze_commits_parent_is_refused(tmp_path):
    root, path, pin = make_repo(tmp_path)
    path.write_text(prereg_text("1" * 40))
    git(root, "commit", "-qam", "repin")
    with pytest.raises(ft.ScoredRefusalError, match="not the freeze commit's parent"):
        ft.check(path, root)


def test_a_prereg_without_a_pin_is_refused(tmp_path):
    root, path, _ = make_repo(tmp_path)
    path.write_text(prereg_text("x").replace("Code pinned at x.", ""))
    git(root, "commit", "-qam", "unpinned")
    with pytest.raises(ft.ScoredRefusalError, match="no 'Code pinned at"):
        ft.check(path, root)


def test_the_cases_are_ninety_eight_on_the_seven_named_maps_and_never_repeat():
    cases = fc.scored_cases()
    assert len(cases) == 98 and {c.level for c in cases} == set(fc.HELD_OUT_MAPS)
    assert {c.seed for c in cases} == set(range(2001, 2015))
    ft.require_levels(cases)


def test_any_level_outside_the_seven_or_a_repeated_map_and_seed_is_refused():
    other = Case("MAP20", 2001, 3, CutSetting.NONE)
    with pytest.raises(ft.ScoredRefusalError, match="MAP20"):
        ft.require_levels([other])
    with pytest.raises(ft.ScoredRefusalError, match="MAP01"):
        ft.require_levels([Case("MAP01", 2001, 3, CutSetting.NONE)])
    twice = Case("MAP04", 2001, 3, CutSetting.NONE)
    with pytest.raises(ft.ScoredRefusalError, match="twice"):
        ft.require_levels([twice, twice])


class FakeSpark:
    """Plays a batch with a hidden rule; can fail a case's games a number of times."""

    def __init__(self, fail_cases=None):
        self.order, self.fail = [], dict(fail_cases or {})

    def play_many(self, pairs, on_result):
        for card, case in pairs:
            self.order.append((card.card_id, case))
            left = self.fail.get((card.card_id, case), 0)
            graded = left == 0
            if not graded:
                self.fail[(card.card_id, case)] = left - 1
            share = 0.2 + (0.1 if card.lessons else 0.0)
            on_result(
                card, case,
                GameResult(case, card.card_id, Grade.GRADED if graded else Grade.UNGRADED,
                           False, share, 0, False, 0, 0, None if graded else "SparkApiError"),
            )  # fmt: skip


def test_the_arms_are_interleaved_within_each_case():
    spark = FakeSpark()
    cases = fc.scored_cases()[:8]
    ft.play_scored(spark, cases, batch_cases=4)
    ids = [fc.NO_CARD.card_id, fc.MINED_CARD.card_id, fc.STRONG_CARD.card_id]
    assert [c for c, _ in spark.order[:3]] == ids and len({k for _, k in spark.order[:3]}) == 1
    assert [k for _, k in spark.order[:6:3]] == [cases[0], cases[1]]


def test_an_ungraded_game_is_replayed_up_to_three_times_then_the_case_is_dropped_from_all_arms():
    cases = fc.scored_cases()[:20]
    mined = fc.MINED_CARD.card_id
    spark = FakeSpark({(mined, cases[0]): 2, (mined, cases[1]): 99})
    scores = ft.play_scored(spark, cases, batch_cases=4)
    assert scores["mined"][cases[0]].grade == Grade.GRADED  # fixed on the second replay
    assert scores["mined"][cases[1]].grade == Grade.UNGRADED  # 1 play + 3 replays, still ungraded
    played = [k for c, k in spark.order if c == mined and k == cases[1]]
    assert len(played) == 1 + ft.MAX_REPLAYS
    kept, dropped = ft.drop_incomplete(scores, cases)
    assert dropped == [cases[1]] and cases[1] not in kept and len(kept) == 19


def test_more_than_ten_percent_of_cases_dropped_makes_the_run_incomplete():
    cases = fc.scored_cases()[:20]
    fail = {(fc.MINED_CARD.card_id, case): 99 for case in cases[:3]}
    scores = ft.play_scored(FakeSpark(fail), cases, batch_cases=4)
    with pytest.raises(ft.IncompleteRunError):
        ft.drop_incomplete(scores, cases)


def report():
    return ft.CheckReport("c" * 40, "f" * 40, "p" * 40, "d" * 64, {"Mined card": "a" * 64})


def test_the_results_file_holds_ids_labels_and_intervals_and_no_card_text():
    cases = fc.scored_cases()
    scores = ft.play_scored(FakeSpark(), cases, batch_cases=7)
    document = ft.results_document(report(), scores, cases, {"model": "m", "spend": {"calls": 0}})
    text = json.dumps(document)
    for card in (fc.MINED_CARD, fc.STRONG_CARD):
        for lesson in card.lessons:
            assert lesson.instead not in text and lesson.went_wrong not in text
    assert document["cases_scored"] == 98 and document["cases_dropped"] == 0
    assert [row["role"] for row in document["rows"]] == ["floor", "under_test", "reference"]
    assert document["rows"][0]["label"] == "no card"
    assert document["code_commit"] == "c" * 40 and document["claims"]["C1"]["per_map"]
    assert set(document["claims"]["C1"]["per_map"]) == set(fc.HELD_OUT_MAPS)


def test_the_results_document_passes_the_results_content_gate():
    cases = fc.scored_cases()
    scores = ft.play_scored(FakeSpark(), cases, batch_cases=7)
    document = ft.results_document(report(), scores, cases, {"model": "m", "spend": {"calls": 0}})
    gate_path = Path(__file__).resolve().parents[2] / "scripts" / "gates"
    sys.path.insert(0, str(gate_path))
    import check_results_content as gate  # noqa: PLC0415 - the gate script lives outside src

    assert gate.findings_in("evolve-card.json", json.loads(json.dumps(document))) == []
    assert "result" in document and "sentence" not in document


def per_case(gain, noise_by_map=None):
    cases = fc.scored_cases()
    base = {c: 0.0 for c in cases}
    shifted = {c: gain + (noise_by_map or {}).get(c.level, 0.0) for c in cases}
    return base, shifted


def test_better_needs_both_intervals_above_zero_and_the_bar_needs_a_mean_of_a_tenth():
    none, mined = per_case(0.3)
    result = sf.compare(mined, none)
    assert result["word"] == "better" and result["mean_difference"] == pytest.approx(0.3)
    assert all(low > 0 for low, _ in (result["map_interval"], result["case_interval"]))
    claims = sf.analyze({"none": none, "mined": mined, "strong": mined})["claims"]
    assert claims["C1"]["supports_the_card"] is True
    small_none, small_mined = per_case(0.05)
    assert (
        sf.analyze({"none": small_none, "mined": small_mined, "strong": small_mined})["claims"][
            "C1"
        ]["supports_the_card"]
        is False
    )


def test_a_gain_on_five_maps_that_reverses_on_two_reads_tie_not_better():
    cases = fc.scored_cases()
    mined = {c: (0.3 if c.level in fc.HELD_OUT_MAPS[:5] else -0.5) for c in cases}
    none = {c: 0.0 for c in cases}
    assert sf.compare(mined, none)["word"] == "tie"


def test_the_sentence_never_uses_the_words_the_pitch_may_not_use_and_names_the_interval():
    none, mined = per_case(0.3)
    strong = {c: 0.1 for c in none}
    supported = sf.analyze({"none": none, "mined": mined, "strong": strong})["result"]
    assert "raised Muse Spark's fitness by 0.30" in supported and "interval" in supported
    assert "against 0.10 for a hand-written card" in supported
    flat = sf.analyze({"none": none, "mined": none, "strong": strong})["result"]
    assert flat.startswith("A mined card did not measurably beat no card at this size")
    worse = sf.analyze({"none": mined, "mined": none, "strong": strong})["result"]
    assert "scored below no card" in worse
    for sentence in (supported, flat, worse):
        assert not any(word in sentence.lower() for word in FORBIDDEN)


def test_a_tie_with_a_mean_between_five_and_ten_hundredths_says_no_measurable_gain_not_trend():
    cases = fc.scored_cases()
    # a gain on a fifth of the cases, a loss on others: a mean of about 0.06 and a case interval
    # that reaches below zero
    mined = {c: (0.7 if i % 5 == 0 else (-0.3 if i % 3 == 1 else 0.0)) for i, c in enumerate(cases)}
    none = {c: 0.0 for c in cases}
    result = sf.compare(mined, none)
    assert 0.05 <= result["mean_difference"] < 0.10 and result["word"] == "tie"
    sentence = sf.analyze({"none": none, "mined": mined, "strong": none})["result"]
    assert "No measurable gain at this size." in sentence and "trend" not in sentence.lower()


def test_unpaired_cases_are_refused():
    cases = fc.scored_cases()
    with pytest.raises(sf.UnpairedCasesError):
        sf.compare({c: 0.0 for c in cases}, {c: 0.0 for c in cases[:-1]})


def test_the_frozen_cards_equal_the_sensitivity_checks_strong_card_and_the_gen0_best_text():
    import card_sensitivity as cs

    assert fc.STRONG_CARD == cs.STRONG_CARD
    assert fc.card_sha256(fc.MINED_CARD).startswith("5984390e1d7c")
    assert fc.card_sha256(fc.STRONG_CARD).startswith("7cf218224ac8")


def test_the_real_prereg_quotes_both_cards_exactly_and_names_the_seven_maps():
    path = Path(__file__).resolve().parents[2] / "prereg" / "2026-10-29-evolve-card.md"
    text = path.read_text()
    hashes = ft.require_cards(text)
    assert hashes["Mined card"] == fc.card_sha256(fc.MINED_CARD)
    assert all(level in text for level in fc.HELD_OUT_MAPS) and "MAP20" in text
    assert "results/evolve-card.json" in text and "final_test.py" in text
    assert not any(word in ft.RESULTS_SCHEMA for word in FORBIDDEN)

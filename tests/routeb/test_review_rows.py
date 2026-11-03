"""Nightly rows from PR-derived lessons: positive "this lesson was needed here" examples.

Failure guarded against: Silent Fallback (a row for a lesson nobody confirmed, or an answer worded
beyond the stored lesson). Synthetic lessons only.
"""

from symbiont.miner.lesson_context import AppliesTo, AuthoredLesson, LessonKind
from symbiont.routeb.review_rows import KIND, MAX_FILES, review_rows

URL = "https://github.com/acme/shop/pull/412"


def pr_lesson(**changes):
    base = {
        "ident": "w-pr412",
        "text": "Refund amounts are integer cents; reviewers rejected float math in refund.py.",
        "kind": LessonKind.CORRECTION,
        "files": ("src/billing/refund.py",),
        "source_label": "from PR #412 review",
        "source_url": URL,
    }
    return AuthoredLesson(**(base | changes))


def test_a_pr_lesson_becomes_a_situation_to_lesson_row_per_file():
    lesson = pr_lesson(files=("src/billing/refund.py", "src/billing/ledger.py"))

    rows = review_rows("shop", [lesson])

    assert [row.kind for row in rows] == [KIND, KIND] and rows[0].lesson_id == "w-pr412"
    user, answer = rows[0].messages[1]["content"], rows[0].messages[2]["content"]
    assert "about to edit `src/billing/refund.py`" in user
    assert answer == f"Before that, remember (from PR #412 review): {lesson.text}"
    assert "ledger.py" in rows[1].messages[1]["content"]


def test_a_lesson_without_a_pr_link_is_not_human_confirmed_and_gives_no_row():
    reflected = pr_lesson(source_url="", source_label="from reflection")

    assert review_rows("shop", [reflected]) == []


def test_files_are_capped_and_areas_then_the_repo_stand_in_when_no_file_is_named():
    many = pr_lesson(files=tuple(f"src/a{n}.py" for n in range(MAX_FILES + 4)))
    by_area = pr_lesson(files=(), applies=AppliesTo(areas=("src/billing/",)))
    bare = pr_lesson(files=())

    assert len(review_rows("shop", [many])) == MAX_FILES
    assert "under `src/billing/`" in review_rows("shop", [by_area])[0].messages[1]["content"]
    assert "start a change" in review_rows("shop", [bare])[0].messages[1]["content"]

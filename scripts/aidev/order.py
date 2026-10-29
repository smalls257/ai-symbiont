"""Is `pr_commits` row order the order the commits were made? Checks that need no timestamps.

AIDev has no commit timestamps or parent links, so "later" means "a later row" only if row order
is chronological; the votes are published, not assumed. Checks: an added file is modified only in
later rows; a comment's head commit is never an earlier row than its original commit; Copilot's
"Initial plan" commit is the first row. Pure: per-PR facts in, votes out.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class CommitFacts:
    """What a commit row says without its patch text."""

    sha: str
    statuses: dict[str, str]  # filename -> added | modified | removed | renamed
    opens_with_plan: bool  # message begins "Initial plan"


def order_votes(
    commits: Sequence[CommitFacts], comment_shas: Sequence[tuple[str, str]]
) -> Counter[str]:
    """Votes for and against chronological row order; `comment_shas` holds (head, original)."""
    votes: Counter[str] = Counter()
    _vote_added_first(commits, votes)
    index_of = {commit.sha: i for i, commit in enumerate(commits)}
    for head, original in comment_shas:
        if head in index_of and original in index_of:
            later = index_of[head] >= index_of[original]
            votes[f"head_not_before_original_{'agree' if later else 'disagree'}"] += 1
    if len(commits) > 1:
        for i, commit in enumerate(commits):
            if commit.opens_with_plan:
                votes[f"plan_first_{'agree' if i == 0 else 'disagree'}"] += 1
    return votes


def _vote_added_first(commits: Sequence[CommitFacts], votes: Counter[str]) -> None:
    added_at: dict[str, int] = {}
    for i, commit in enumerate(commits):
        for name, status in commit.statuses.items():
            if status == "added":
                added_at.setdefault(name, i)
    for i, commit in enumerate(commits):
        for name, status in commit.statuses.items():
            if status == "modified" and name in added_at:
                agree = added_at[name] < i
                votes[f"added_before_modified_{'agree' if agree else 'disagree'}"] += 1

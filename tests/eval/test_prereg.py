"""The prereg format and the frozen check, driven by a fake git view (airplane mode)."""

import hashlib
from pathlib import Path

import pytest

from symbiont.eval.prereg import PathState, PreregNotFrozenError, parse_prereg, verify_frozen

GOOD = (
    "# Pre-registration: a run\n\n**FROZEN 2026-10-27T10:00:00Z.** Committed alone.\n\n"
    "Claim tags: [measured]\n"
)
AMENDMENT = (
    "# Amendment 1 to the run\n\n**FROZEN 2026-10-28.** Fix.\n\n"
    "Amends: prereg/2026-10-27-run.md\n\nClaim tags: [measured]\n"
)


class FakeGit:
    def __init__(self, states: dict[str, PathState]) -> None:
        self.states = states

    def root(self) -> Path:
        return Path("/repo")

    def state(self, path: Path) -> PathState:
        return self.states.get(path.name, PathState.UNTRACKED)

    def adding_commit(self, path: Path) -> str:
        return f"sha-of-{path.name}"


def reader(files: dict[str, str]):
    return lambda path: files[path.name].encode()


def test_a_well_formed_prereg_parses():
    parsed = parse_prereg(GOOD, name="2026-10-27-run.md")
    assert (parsed.title, parsed.frozen_on, parsed.amends) == (
        "Pre-registration: a run",
        "2026-10-27",
        None,
    )


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("no title\n**FROZEN 2026-10-27.**\nClaim tags: x\n", "title"),
        ("# T\n\nnothing frozen here\nClaim tags: x\n", "FROZEN"),
        ("# T\n\n**FROZEN 2026-10-27.**\n", "Claim tags"),
    ],
)
def test_a_missing_required_field_is_refused(text, reason):
    with pytest.raises(PreregNotFrozenError, match=reason):
        parse_prereg(text, name="x.md")


def test_a_clean_prereg_is_frozen_with_its_hash_and_commit():
    git = FakeGit({"2026-10-27-run.md": PathState.CLEAN})
    frozen = verify_frozen(
        Path("/repo/prereg/2026-10-27-run.md"), git, reader({"2026-10-27-run.md": GOOD})
    )
    assert frozen.sha256 == hashlib.sha256(GOOD.encode()).hexdigest()
    assert frozen.commit == "sha-of-2026-10-27-run.md"


@pytest.mark.parametrize("state", [PathState.UNTRACKED, PathState.STAGED, PathState.MODIFIED])
def test_a_prereg_that_is_not_clean_is_refused_naming_file_and_reason(state):
    git = FakeGit({"2026-10-27-run.md": state})
    with pytest.raises(PreregNotFrozenError, match=f"2026-10-27-run.md.*{state.value}"):
        verify_frozen(
            Path("/repo/prereg/2026-10-27-run.md"), git, reader({"2026-10-27-run.md": GOOD})
        )


def test_an_amendment_needs_its_original_frozen_too():
    files = {"2026-10-27-run.md": GOOD, "2026-10-28-run-fix.md": AMENDMENT}
    amendment = Path("/repo/prereg/2026-10-28-run-fix.md")
    clean = FakeGit(
        {"2026-10-27-run.md": PathState.CLEAN, "2026-10-28-run-fix.md": PathState.CLEAN}
    )
    assert verify_frozen(amendment, clean, reader(files)).original.name == "2026-10-27-run.md"
    original_edited = FakeGit(
        {"2026-10-27-run.md": PathState.MODIFIED, "2026-10-28-run-fix.md": PathState.CLEAN}
    )
    with pytest.raises(PreregNotFrozenError, match="2026-10-27-run.md"):
        verify_frozen(amendment, original_edited, reader(files))


def test_an_amendment_loop_is_refused():
    loop = AMENDMENT.replace("2026-10-27-run.md", "2026-10-28-run-fix.md")
    git = FakeGit({"2026-10-28-run-fix.md": PathState.CLEAN})
    with pytest.raises(PreregNotFrozenError, match="deeper"):
        verify_frozen(
            Path("/repo/prereg/2026-10-28-run-fix.md"), git, reader({"2026-10-28-run-fix.md": loop})
        )


def test_an_amendment_file_name_must_start_with_a_date():
    with pytest.raises(PreregNotFrozenError, match="date"):
        parse_prereg(AMENDMENT, name="prereg/fix.md")

"""The repository registry: asked, given, declined, muted, announced; a bad file raises."""

import pytest

from symbiont.store.repos import RepoRegistry, RepoRegistryError, RepoStance

pytestmark = pytest.mark.periphery


def test_a_repository_nobody_answered_for_has_no_stance(tmp_path):
    assert RepoRegistry(tmp_path).stance("demo") is None


def test_the_answer_is_remembered_per_repository_across_instances(tmp_path):
    RepoRegistry(tmp_path).record_stance("demo", RepoStance.GIVEN)
    RepoRegistry(tmp_path).record_stance("other", RepoStance.DECLINED)

    again = RepoRegistry(tmp_path)
    assert again.stance("demo") is RepoStance.GIVEN
    assert again.stance("other") is RepoStance.DECLINED


def test_forgetting_a_project_asks_again(tmp_path):
    registry = RepoRegistry(tmp_path)
    registry.record_stance("demo", RepoStance.GIVEN)

    registry.forget_project("demo")

    assert registry.stance("demo") is None


def test_muting_is_idempotent_reversible_and_scoped_to_the_project(tmp_path):
    registry = RepoRegistry(tmp_path)
    trouble = ("failed_command", "pytest", "tests/a.py", "ImportError")

    registry.mute("demo", trouble)
    registry.mute("demo", trouble)

    assert registry.muted("demo") == {trouble}
    assert registry.muted("other") == frozenset()
    registry.unmute("demo", trouble)
    assert registry.muted("demo") == frozenset()


def test_the_nightly_announcement_is_made_once(tmp_path):
    registry = RepoRegistry(tmp_path)
    assert not registry.nightly_announced("demo")

    registry.announce_nightly("demo")

    assert RepoRegistry(tmp_path).nightly_announced("demo")


def test_a_file_that_is_not_a_registry_raises_naming_it(tmp_path):
    (tmp_path / "repos.json").write_text('{"projects": {"demo": {"stance": "maybe"}}}')

    with pytest.raises(RepoRegistryError, match="repos.json"):
        RepoRegistry(tmp_path).stance("demo")

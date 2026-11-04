import pytest


@pytest.fixture(autouse=True)
def isolated_home_and_hub(tmp_path_factory, monkeypatch):
    """Nightly code reads HOME and the Hugging Face cache; a test never sees the real ones."""
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("HF_HOME", raising=False)

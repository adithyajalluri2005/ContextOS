import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Every test gets its own CONTEXTOS_HOME, so no test touches the real ~/.contextos."""
    home = tmp_path / "contextos-home"
    monkeypatch.setenv("CONTEXTOS_HOME", str(home))
    return home

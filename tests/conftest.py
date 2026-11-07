import pytest

# Real settings that must never reach a test: with them a test could use a real
# key or call a real AI service.
REAL_SETTINGS = (
    "CONTEXTOS_PROVIDER",
    "CONTEXTOS_MODEL",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OLLAMA_API_KEY",
    "OLLAMA_HOST",
)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Every test gets its own CONTEXTOS_HOME, so no test touches the real ~/.contextos.
    Real AI settings and keys are removed as well; tests that need one set it themselves."""
    for name in REAL_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    home = tmp_path / "contextos-home"
    monkeypatch.setenv("CONTEXTOS_HOME", str(home))
    return home

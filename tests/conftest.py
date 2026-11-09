"""Shared test setup."""

import pytest


@pytest.fixture(autouse=True)
def _private_home(tmp_path, monkeypatch):
    """Every test gets its own empty CONTEXTOS_HOME, so no test can touch your real data."""
    monkeypatch.setenv("CONTEXTOS_HOME", str(tmp_path / "contextos-home"))

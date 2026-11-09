"""Tests for local storage. All data here is made up."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest

from contextos.context import CodeSnippet, Context, FileRef
from contextos.store import Store, default_db_path

BASE = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


def make(title: str, minutes: int = 0, **extra) -> Context:
    return Context(title=title, summary=f"Summary of {title}", created_at=BASE + timedelta(minutes=minutes), **extra)


@pytest.fixture
def store(tmp_path) -> Store:
    return Store(tmp_path / "test.db")


def test_default_path_uses_contextos_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTEXTOS_HOME", str(tmp_path / "home"))
    assert default_db_path() == tmp_path / "home" / "contextos.db"
    Store()
    assert (tmp_path / "home" / "contextos.db").exists()


def test_default_path_without_contextos_home(monkeypatch, tmp_path):
    monkeypatch.delenv("CONTEXTOS_HOME")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    assert default_db_path() == tmp_path / ".contextos" / "contextos.db"


def test_save_gives_new_id_and_get_returns_same_context(store):
    ctx = make(
        "Blog move",
        decisions=["Use Hugo"],
        files=[FileRef(path="config.toml", note="settings")],
        code=[CodeSnippet(content="hugo", language="bash")],
        source_tool="claude-code",
    )
    saved = store.save(ctx)
    assert saved.id == "1"
    assert store.get("1") == saved
    assert saved.model_copy(update={"id": None}) == ctx


def test_save_ignores_existing_id_and_adds_new_entry(store):
    first = store.save(make("A"))
    second = store.save(first)
    assert (first.id, second.id) == ("1", "2")


@pytest.mark.parametrize("bad_id", ["99", "abc", "", "-1", "1; DROP TABLE contexts"])
def test_get_unknown_or_bad_id_returns_none(store, bad_id):
    store.save(make("A"))
    assert store.get(bad_id) is None


def test_recent_is_newest_first_and_respects_limit(store):
    store.save(make("old", 0))
    store.save(make("newest", 20))
    store.save(make("middle", 10))
    assert [c.title for c in store.recent()] == ["newest", "middle", "old"]
    assert [c.title for c in store.recent(limit=1)] == ["newest"]


def test_recent_same_time_uses_save_order(store):
    store.save(make("first"))
    store.save(make("second"))
    assert [c.title for c in store.recent()] == ["second", "first"]


def test_recent_filters_by_source_tool(store):
    store.save(make("a", source_tool="claude-code"))
    store.save(make("b", source_tool="cursor"))
    store.save(make("c"))
    assert [c.title for c in store.recent(source_tool="cursor")] == ["b"]


def test_recent_empty_store(store):
    assert store.recent() == []


def test_search_needs_every_word_in_any_field(store):
    store.save(make("Blog move", decisions=["Use Hugo"]))
    store.save(make("Auth bug", next_steps=["Fix token expiry in login"]))
    assert [c.title for c in store.search("hugo blog")] == ["Blog move"]
    assert [c.title for c in store.search("TOKEN login")] == ["Auth bug"]
    assert store.search("hugo token") == []


def test_search_finds_file_paths_and_code(store):
    store.save(make("A", files=[FileRef(path="src/auth.py")], code=[CodeSnippet(content="def refresh_token(): ...")]))
    assert len(store.search("auth.py")) == 1
    assert len(store.search("refresh_token")) == 1


def test_search_does_not_match_fixed_header_words(store):
    store.save(make("A"))
    assert store.search("continue") == []
    assert store.search("saved") == []


def test_search_is_case_insensitive_beyond_english(store):
    store.save(make("Ünïcode Straße"))
    assert len(store.search("ÜNÏCODE")) == 1


def test_search_treats_like_symbols_as_plain_text(store):
    store.save(make("100% done"))
    store.save(make("plain"))
    assert [c.title for c in store.search("%")] == ["100% done"]
    assert store.search("_") == []
    assert store.search("!") == []


def test_empty_search_finds_nothing(store):
    store.save(make("A"))
    assert store.search("   ") == []


def test_delete(store):
    store.save(make("A"))
    assert store.delete("1") is True
    assert store.get("1") is None
    assert store.delete("1") is False
    assert store.delete("abc") is False


def test_data_survives_reopening(tmp_path):
    path = tmp_path / "keep.db"
    Store(path).save(make("A"))
    assert [c.title for c in Store(path).recent()] == ["A"]


def test_schema_version_is_set(store):
    with closing(sqlite3.connect(store.path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1

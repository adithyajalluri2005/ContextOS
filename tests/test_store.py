import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from contextos.pack import Message
from contextos.store import (
    SCHEMA_VERSION,
    ConversationIn,
    Store,
    contextos_home,
    default_db_path,
)

T0 = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)


def make_conv(source_id="c-1", tool="chatgpt", messages=None, **extra) -> ConversationIn:
    if messages is None:
        messages = [
            Message(role="user", content="How do I move my chat?", created_at=T0),
            Message(role="assistant", content="Export it, then make a pack.", created_at=T0 + timedelta(minutes=1)),
        ]
    data = {
        "source_tool": tool,
        "source_id": source_id,
        "title": "Moving chats",
        "created_at": T0,
        "updated_at": T0 + timedelta(minutes=1),
        "messages": messages,
    }
    data.update(extra)
    return ConversationIn(**data)


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "test.db") as s:
        yield s


# --- paths -----------------------------------------------------------------


def test_contextos_home_env_changes_default_path(isolated_home):
    assert contextos_home() == isolated_home
    assert default_db_path() == isolated_home / "contextos.db"


def test_default_home_is_dot_contextos_in_user_home(monkeypatch):
    monkeypatch.delenv("CONTEXTOS_HOME", raising=False)
    assert default_db_path() == Path.home() / ".contextos" / "contextos.db"


def test_store_without_path_creates_db_in_home(isolated_home):
    assert not isolated_home.exists()
    with Store() as s:
        assert s.path == isolated_home / "contextos.db"
    assert (isolated_home / "contextos.db").is_file()


# --- saving ----------------------------------------------------------------


def test_save_and_get_round_trip(store):
    conv_id, status = store.save(make_conv(url="https://chatgpt.com/c/c-1"))
    assert status == "created"
    got = store.get(conv_id)
    assert got.source_tool == "chatgpt" and got.source_id == "c-1"
    assert got.title == "Moving chats"
    assert got.url == "https://chatgpt.com/c/c-1"
    assert got.created_at == T0
    assert got.message_count == 2
    assert [m.role for m in got.messages] == ["user", "assistant"]
    assert got.messages[1].content == "Export it, then make a pack."
    assert got.messages[1].created_at == T0 + timedelta(minutes=1)


def test_same_import_twice_does_not_duplicate(store):
    first_id, first = store.save(make_conv())
    second_id, second = store.save(make_conv())
    assert (first, second) == ("created", "unchanged")
    assert first_id == second_id
    assert store.count() == 1
    assert store.get(first_id).message_count == 2


def test_changed_conversation_is_updated_in_place(store):
    conv_id, _ = store.save(make_conv())
    longer = make_conv(
        title="Moving chats (continued)",
        messages=[
            Message(role="user", content="How do I move my chat?"),
            Message(role="assistant", content="Export it, then make a pack."),
            Message(role="user", content="And for Claude Code?"),
        ],
    )
    same_id, status = store.save(longer)
    assert status == "updated"
    assert same_id == conv_id
    assert store.count() == 1
    got = store.get(conv_id)
    assert got.title == "Moving chats (continued)"
    assert [m.content for m in got.messages][-1] == "And for Claude Code?"
    assert got.message_count == 3


def test_same_id_from_different_tools_are_separate(store):
    store.save(make_conv(source_id="same", tool="chatgpt"))
    store.save(make_conv(source_id="same", tool="claude-ai"))
    assert store.count() == 2


def test_message_order_is_kept(store):
    msgs = [Message(role="user" if i % 2 == 0 else "assistant", content=f"m{i}") for i in range(25)]
    conv_id, _ = store.save(make_conv(messages=msgs))
    assert [m.content for m in store.get(conv_id).messages] == [f"m{i}" for i in range(25)]


def test_conversation_without_messages_or_dates(store):
    conv = ConversationIn(source_tool="claude-code", source_id="s-1")
    conv_id, status = store.save(conv)
    assert status == "created"
    got = store.get(conv_id)
    assert got.messages == [] and got.message_count == 0
    assert got.title is None and got.created_at is None


def test_other_time_zones_are_stored_as_the_same_instant(store):
    ist = timezone(timedelta(hours=5, minutes=30))
    conv_id, _ = store.save(make_conv(created_at=datetime(2026, 11, 1, 15, 30, tzinfo=ist)))
    assert store.get(conv_id).created_at == T0


def test_failed_save_leaves_nothing_behind(store, monkeypatch):
    conv = make_conv()
    store.save(conv)
    bad = make_conv(title="changed")
    # Break the message insert halfway through the transaction.
    bad.messages.append(Message.model_construct(role="robot", content="x", created_at=None))
    with pytest.raises(sqlite3.IntegrityError):
        store.save(bad)
    got = store.get(1)
    assert got.title == "Moving chats"
    assert got.message_count == 2


# --- reading ---------------------------------------------------------------


def test_list_is_newest_first_and_filters_by_source(store):
    store.save(make_conv("old", updated_at=T0))
    store.save(make_conv("new", updated_at=T0 + timedelta(days=2)))
    store.save(make_conv("claude", tool="claude-ai", updated_at=T0 + timedelta(days=1)))

    assert [c.source_id for c in store.list_conversations()] == ["new", "claude", "old"]
    only = store.list_conversations(source_tool="claude-ai")
    assert [c.source_id for c in only] == ["claude"]
    assert only[0].message_count == 2


def test_get_unknown_id_returns_none(store):
    assert store.get(999) is None


def test_data_survives_reopening(tmp_path):
    path = tmp_path / "persist.db"
    with Store(path) as s:
        conv_id, _ = s.save(make_conv())
    with Store(path) as s:
        assert s.get(conv_id).title == "Moving chats"
        _, status = s.save(make_conv())
        assert status == "unchanged"


# --- schema ----------------------------------------------------------------


def test_schema_version_is_recorded(tmp_path):
    path = tmp_path / "v.db"
    Store(path).close()
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    conn.close()


def test_newer_database_is_refused(tmp_path):
    path = tmp_path / "future.db"
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.close()
    with pytest.raises(RuntimeError, match="newer ContextOS"):
        Store(path)


def test_input_is_validated():
    with pytest.raises(ValidationError):
        ConversationIn(source_tool="", source_id="x")
    with pytest.raises(ValidationError):
        ConversationIn(source_tool="chatgpt", source_id="x", created_at=datetime(2026, 1, 1))

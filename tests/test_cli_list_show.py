from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from contextos.cli import app
from contextos.pack import Message
from contextos.store import ConversationIn, Store
from fixtures.make_fixtures import CHATGPT_ZIP

runner = CliRunner()


def at(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 3, day, hour, 0, tzinfo=timezone.utc)


@pytest.fixture
def ids():
    """Three made-up conversations from different tools. Returns their store IDs by short name."""
    convs = {
        "trip": ConversationIn(
            source_tool="chatgpt",
            source_id="gpt-1",
            title="Plan a weekend in Pune",
            url="https://chatgpt.com/c/gpt-1",
            created_at=at(1),
            updated_at=at(2),
            messages=[
                Message(role="user", content="Plan two days in Pune.", created_at=at(1, 9)),
                Message(role="assistant", content="Day 1: Shaniwar Wada.\nDay 2: Sinhagad fort.", created_at=at(1, 10)),
            ],
        ),
        "sql": ConversationIn(
            source_tool="claude-ai",
            source_id="cl-1",
            title="Speed up a slow SQL query",
            created_at=at(5),
            messages=[
                Message(role="user", content="My join is slow."),
                Message(role="assistant", content="Add an index on orders.customer_id."),
                Message(role="user", content="Done, thanks."),
            ],
        ),
        "untitled": ConversationIn(
            source_tool="claude-code",
            source_id="cc-1",
            title=None,
            created_at=at(3),
            messages=[Message(role="system", content="Working folder: D:/demo")],
        ),
    }
    with Store() as store:
        return {name: store.save(c)[0] for name, c in convs.items()}


def run(*args: str):
    return runner.invoke(app, list(args))


def data_lines(output: str) -> list[str]:
    """Table rows only: skip the header, the blank line and the count line."""
    lines = output.splitlines()
    return [ln for ln in lines[1:] if ln.strip() and not ln.endswith("conversation(s).")]


# --- list --------------------------------------------------------------------


def test_list_with_empty_store_says_how_to_import():
    result = run("list")
    assert result.exit_code == 0
    assert "No conversations yet" in result.output
    assert "contextos import" in result.output


def test_list_shows_all_columns_newest_first(ids):
    result = run("list")
    assert result.exit_code == 0, result.output
    header = result.output.splitlines()[0].split()
    assert header == ["ID", "SOURCE", "DATE", "MESSAGES", "TITLE"]

    rows = data_lines(result.output)
    # Newest by last change (or start date when never updated): sql (Mar 5), untitled (Mar 3), trip (Mar 2).
    assert [r.split()[0] for r in rows] == [str(ids["sql"]), str(ids["untitled"]), str(ids["trip"])]

    sql = rows[0].split(None, 4)
    assert sql == [str(ids["sql"]), "claude-ai", "2026-03-05", "3", "Speed up a slow SQL query"]
    trip = rows[2].split(None, 4)
    assert trip == [str(ids["trip"]), "chatgpt", "2026-03-02", "2", "Plan a weekend in Pune"]
    assert rows[1].endswith("(untitled)")
    assert "3 conversation(s)." in result.output


def test_list_filters_by_source(ids):
    result = run("list", "--source", "chatgpt")
    assert result.exit_code == 0, result.output
    rows = data_lines(result.output)
    assert len(rows) == 1
    assert "Plan a weekend in Pune" in rows[0]
    assert "Speed up" not in result.output

    short = run("list", "-s", "claude-code")
    assert short.exit_code == 0
    assert len(data_lines(short.output)) == 1


def test_list_filter_with_no_matches(ids):
    with Store() as store:
        store._conn.execute("DELETE FROM conversations WHERE source_tool = 'chatgpt'")
        store._conn.commit()
    result = run("list", "--source", "chatgpt")
    assert result.exit_code == 0
    assert "No conversations from chatgpt." in result.output


def test_list_rejects_unknown_source(ids):
    result = run("list", "--source", "gemini")
    assert result.exit_code == 2
    assert "unknown source 'gemini'" in result.output
    assert "chatgpt, claude-ai, claude-code" in result.output


def test_list_shortens_long_titles_and_flattens_new_lines():
    with Store() as store:
        store.save(ConversationIn(source_tool="chatgpt", source_id="long", title="word " * 40))
        store.save(ConversationIn(source_tool="chatgpt", source_id="nl", title="first line\nsecond line"))
    result = run("list")
    assert result.exit_code == 0
    rows = data_lines(result.output)
    assert any(r.endswith("...") for r in rows)
    assert all(len(r.split(None, 4)[-1]) <= 60 for r in rows)
    assert any(r.endswith("first line second line") for r in rows)


def test_list_after_real_fixture_import():
    imported = run("import", "chatgpt", str(CHATGPT_ZIP))
    assert imported.exit_code == 0, imported.output
    result = run("list", "--source", "chatgpt")
    assert result.exit_code == 0
    assert "Plan a trip to Goa" in result.output
    assert "CSV cleanup in Python" in result.output


# --- show --------------------------------------------------------------------


def test_show_prints_header_and_messages_in_order(ids):
    result = run("show", str(ids["trip"]))
    assert result.exit_code == 0, result.output
    out = result.output
    lines = out.splitlines()
    assert lines[0] == "Plan a weekend in Pune"
    assert "Source:   chatgpt (gpt-1)" in out
    assert "Started:  2026-03-01 12:00 UTC" in out
    assert "Updated:  2026-03-02 12:00 UTC" in out
    assert "Link:     https://chatgpt.com/c/gpt-1" in out
    assert "Messages: 2" in out

    user_at = out.index("--- user, 2026-03-01 09:00 UTC ---")
    asst_at = out.index("--- assistant, 2026-03-01 10:00 UTC ---")
    assert user_at < out.index("Plan two days in Pune.") < asst_at
    # Multi-line content is printed as is.
    assert "Day 1: Shaniwar Wada.\nDay 2: Sinhagad fort." in out


def test_show_without_times_link_or_title(ids):
    result = run("show", str(ids["sql"]))
    assert result.exit_code == 0
    assert "Link:" not in result.output
    assert "Updated:  -" in result.output
    assert result.output.count("--- user ---") == 2
    assert "--- assistant ---" in result.output

    untitled = run("show", str(ids["untitled"]))
    assert untitled.output.splitlines()[0] == "(untitled)"
    assert "--- system ---" in untitled.output


def test_show_unknown_id_fails_with_hint(ids):
    result = run("show", "9999")
    assert result.exit_code == 1
    assert "no conversation with ID 9999" in result.output
    assert "contextos list" in result.output


def test_show_needs_a_number():
    result = run("show", "abc")
    assert result.exit_code == 2

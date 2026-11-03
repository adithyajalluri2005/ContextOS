import json
import zipfile
from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from contextos.cli import app
from contextos.importers import ImportFailed
from contextos.importers.base import MAX_TOOL_CHARS
from contextos.importers.claude_ai import parse_conversation, read_export
from contextos.store import Store
from fixtures.make_fixtures import CLAUDE_ZIP, claude_conversations, write_claude_zip

runner = CliRunner()


@pytest.fixture(scope="module")
def parsed():
    return read_export(CLAUDE_ZIP)


def by_id(parsed, source_id):
    return next(c for c in parsed.conversations if c.source_id == source_id)


DB = "11111111-aaaa-4000-8000-000000000001"
BRANCHED = "22222222-bbbb-4000-8000-000000000002"
OLDER = "33333333-cccc-4000-8000-000000000003"


# --- the committed test export ---------------------------------------------


def test_committed_zip_matches_generator(tmp_path):
    rebuilt = write_claude_zip(tmp_path / "rebuilt.zip")
    with zipfile.ZipFile(CLAUDE_ZIP) as a, zipfile.ZipFile(rebuilt) as b:
        assert sorted(a.namelist()) == sorted(b.namelist())
        for name in a.namelist():
            assert a.read(name) == b.read(name), f"{name} is out of date; run tests/fixtures/make_fixtures.py"


def test_reads_good_chats_and_skips_bad_ones_with_reasons(parsed):
    assert [c.source_id for c in parsed.conversations] == [DB, BRANCHED, OLDER]
    assert parsed.skipped == [
        "Empty chat: no visible messages",
        "Chat without id: missing conversation id",
    ]


# --- message tree ----------------------------------------------------------


def test_keeps_only_the_branch_the_user_ended_on(parsed):
    conv = by_id(parsed, BRANCHED)
    assert [m.content for m in conv.messages] == [
        "Suggest a name.", "ContextOS.", "Something friendlier?", "Carry.",
    ]


def test_older_export_without_parent_links_keeps_list_order(parsed):
    conv = by_id(parsed, OLDER)
    assert [(m.role, m.content) for m in conv.messages] == [
        ("user", "Hello"), ("assistant", "Hi! How can I help?"),
    ]


def test_loop_in_parent_links_does_not_hang():
    raw = {
        "uuid": "loop",
        "chat_messages": [
            {"uuid": "a", "parent_message_uuid": "b", "sender": "human", "text": "hi",
             "created_at": "2026-11-01T10:00:01Z"},
            {"uuid": "b", "parent_message_uuid": "a", "sender": "assistant", "text": "hello",
             "created_at": "2026-11-01T10:00:00Z"},
        ],
    }
    assert [m.content for m in parse_conversation(raw).messages] == ["hello", "hi"]


# --- message content -------------------------------------------------------


def test_roles_are_mapped(parsed):
    assert [m.role for m in by_id(parsed, DB).messages] == ["user", "assistant"]


def test_thinking_and_raw_tool_results_are_left_out(parsed):
    answer = by_id(parsed, DB).messages[1].content
    assert "SECRET REASONING" not in answer
    assert "RAW SEARCH RESULT" not in answer
    assert answer == (
        "[used tool: web_search]\n\n"
        "Use SQLite for the local tool.\n\n"
        "Move to Postgres only for the team server."
    )


def test_attachments_are_kept_but_cut(parsed):
    question = by_id(parsed, DB).messages[0].content
    assert question.startswith("Should I use SQLite or Postgres? Requirements attached.")
    assert "[attached file: requirements.txt]\nRequirement line." in question
    assert "more characters cut]" in question
    assert len(question) < MAX_TOOL_CHARS + 300
    assert question.endswith("[file: diagram.png]")


def test_text_field_is_used_when_there_are_no_content_blocks():
    raw = {"uuid": "x", "chat_messages": [{"uuid": "1", "sender": "human", "text": "Only text"}]}
    assert parse_conversation(raw).messages[0].content == "Only text"


# --- metadata --------------------------------------------------------------


def test_ids_urls_titles_and_dates(parsed):
    conv = by_id(parsed, DB)
    assert conv.source_tool == "claude-ai"
    assert conv.title == "Database choice for ContextOS"
    assert conv.url == f"https://claude.ai/chat/{DB}"
    assert conv.created_at == datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    assert conv.messages[1].created_at == datetime(2026, 11, 1, 10, 1, tzinfo=timezone.utc)


def test_empty_name_and_dates_without_time_zone(parsed):
    conv = by_id(parsed, OLDER)
    assert conv.title is None
    assert conv.created_at == datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)


# --- other inputs ----------------------------------------------------------


def test_accepts_plain_conversations_json(tmp_path):
    path = tmp_path / "conversations.json"
    path.write_text(json.dumps(claude_conversations()), encoding="utf-8")
    assert len(read_export(path).conversations) == 3


def test_accepts_unzipped_folder(tmp_path):
    folder = tmp_path / "claude-export"
    folder.mkdir()
    (folder / "conversations.json").write_text(json.dumps(claude_conversations()), encoding="utf-8")
    (folder / "projects.json").write_text("[]", encoding="utf-8")
    assert len(read_export(folder).conversations) == 3


def test_zip_without_conversations_gives_clear_error(tmp_path):
    path = tmp_path / "other.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("users.json", "[]")
    with pytest.raises(ImportFailed, match="Is this a Claude data export"):
        read_export(path)


# --- command line ----------------------------------------------------------


def test_cli_import_then_reimport(isolated_home):
    first = runner.invoke(app, ["import", "claude-ai", str(CLAUDE_ZIP)])
    assert first.exit_code == 0, first.output
    assert "Imported 3 conversation(s) from Claude.ai: 3 new, 0 updated, 0 unchanged." in first.output
    assert "Skipped 2:" in first.output

    again = runner.invoke(app, ["import", "claude-ai", str(CLAUDE_ZIP)])
    assert "0 new, 0 updated, 3 unchanged." in again.output

    with Store() as store:
        assert store.count() == 3
        assert {c.source_tool for c in store.list_conversations()} == {"claude-ai"}


def test_chatgpt_and_claude_chats_live_side_by_side(isolated_home):
    from fixtures.make_fixtures import CHATGPT_ZIP

    runner.invoke(app, ["import", "chatgpt", str(CHATGPT_ZIP)])
    runner.invoke(app, ["import", "claude-ai", str(CLAUDE_ZIP)])
    with Store() as store:
        assert store.count() == 6
        assert len(store.list_conversations(source_tool="claude-ai")) == 3


def test_cli_bad_path_exits_with_error(tmp_path):
    result = runner.invoke(app, ["import", "claude-ai", str(tmp_path / "nope.zip")])
    assert result.exit_code == 1
    assert "Error: File not found" in result.output

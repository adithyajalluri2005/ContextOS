import json
import zipfile
from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from contextos.cli import app
from contextos.importers import ImportFailed
from contextos.importers.chatgpt import MAX_TOOL_CHARS, parse_conversation, read_export
from contextos.store import Store
from fixtures.make_fixtures import CHATGPT_ZIP, T, chatgpt_conversations, write_chatgpt_zip

runner = CliRunner()


@pytest.fixture(scope="module")
def parsed():
    return read_export(CHATGPT_ZIP)


def by_title(parsed, title):
    return next(c for c in parsed.conversations if c.title == title)


# --- the committed test export ---------------------------------------------


def test_committed_zip_matches_generator(tmp_path):
    rebuilt = write_chatgpt_zip(tmp_path / "rebuilt.zip")
    with zipfile.ZipFile(CHATGPT_ZIP) as a, zipfile.ZipFile(rebuilt) as b:
        assert sorted(a.namelist()) == sorted(b.namelist())
        for name in a.namelist():
            assert a.read(name) == b.read(name), f"{name} is out of date; run tests/fixtures/make_fixtures.py"


def test_reads_good_chats_and_skips_bad_ones_with_reasons(parsed):
    assert [c.title for c in parsed.conversations] == [
        "Plan a trip to Goa", "CSV cleanup in Python", "No current node",
    ]
    assert parsed.skipped == [
        "Only hidden messages: no visible messages",
        "Broken chat: missing message tree",
    ]


# --- message tree ----------------------------------------------------------


def test_keeps_only_the_branch_the_user_ended_on(parsed):
    trip = by_title(parsed, "Plan a trip to Goa")
    texts = [m.content for m in trip.messages]
    assert texts[2] == "Add a day trip to Dudhsagar falls."
    assert "Make it cheaper." not in texts
    assert "Budget version: hostels only." not in texts
    assert [m.role for m in trip.messages] == ["user", "assistant", "user", "assistant"]


def test_without_current_node_uses_newest_leaf(parsed):
    conv = by_title(parsed, "No current node")
    assert [m.content for m in conv.messages] == ["Name ideas for a cat?", "Mango."]


def test_loop_in_tree_does_not_hang():
    raw = {
        "id": "loop",
        "current_node": "a",
        "mapping": {
            "a": {"id": "a", "parent": "b", "children": [], "message": {
                "author": {"role": "user"}, "content": {"content_type": "text", "parts": ["hi"]}}},
            "b": {"id": "b", "parent": "a", "children": ["a"], "message": None},
        },
    }
    assert [m.content for m in parse_conversation(raw).messages] == ["hi"]


# --- message content -------------------------------------------------------


def test_images_become_a_placeholder(parsed):
    last = by_title(parsed, "Plan a trip to Goa").messages[-1]
    assert last.content == "Here is the updated plan with Dudhsagar on day 2.\n\n[image]"


def test_hidden_settings_and_thoughts_are_left_out(parsed):
    csv = by_title(parsed, "CSV cleanup in Python")
    joined = "\n".join(m.content for m in csv.messages)
    assert "data analyst" not in joined  # custom instructions
    assert "Use pandas dropna" not in joined  # the hidden reasoning text
    assert [m.role for m in csv.messages] == ["user", "assistant", "tool", "assistant"]


def test_code_is_kept_as_a_fenced_block(parsed):
    code = by_title(parsed, "CSV cleanup in Python").messages[1]
    assert code.content.startswith("```python\nimport pandas as pd")
    assert code.content.endswith("\n```")


def test_long_tool_output_is_cut(parsed):
    tool = by_title(parsed, "CSV cleanup in Python").messages[2]
    assert tool.role == "tool"
    assert tool.content.startswith("row ok\n")
    assert "more characters cut]" in tool.content
    assert len(tool.content) < MAX_TOOL_CHARS + 100


# --- metadata --------------------------------------------------------------


def test_ids_urls_and_dates(parsed):
    trip = by_title(parsed, "Plan a trip to Goa")
    assert trip.source_tool == "chatgpt"
    assert trip.source_id == "aaaa1111-0000-4000-8000-000000000001"
    assert trip.url == "https://chatgpt.com/c/aaaa1111-0000-4000-8000-000000000001"
    assert trip.created_at == datetime.fromtimestamp(T, tz=timezone.utc)
    assert trip.updated_at == datetime.fromtimestamp(T + 600, tz=timezone.utc)
    assert trip.messages[0].created_at == datetime.fromtimestamp(T + 10, tz=timezone.utc)
    assert by_title(parsed, "No current node").updated_at is None


# --- other inputs ----------------------------------------------------------


def test_accepts_plain_conversations_json(tmp_path):
    path = tmp_path / "conversations.json"
    path.write_text(json.dumps(chatgpt_conversations()), encoding="utf-8")
    assert len(read_export(path).conversations) == 3


def test_accepts_unzipped_folder_with_split_files(tmp_path):
    convs = chatgpt_conversations()
    (tmp_path / "export").mkdir()
    (tmp_path / "export" / "conversations-000.json").write_text(json.dumps(convs[:1]), encoding="utf-8")
    (tmp_path / "export" / "conversations-001.json").write_text(json.dumps(convs[1:3]), encoding="utf-8")
    (tmp_path / "export" / "shared_conversations.json").write_text("[{}]", encoding="utf-8")
    result = read_export(tmp_path / "export")
    assert len(result.conversations) == 3
    assert result.skipped == []


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        (lambda p: p / "missing.zip", "File not found"),
        (lambda p: (p / "notes.txt").write_text("hi") and p / "notes.txt", "not a ZIP file"),
        (lambda p: (p / "conversations.json").write_text("{not json") and p / "conversations.json",
         "not valid JSON"),
        (lambda p: (p / "conversations.json").write_text("{}") and p / "conversations.json",
         "list of conversations"),
    ],
)
def test_unreadable_exports_give_clear_errors(tmp_path, setup, message):
    with pytest.raises(ImportFailed, match=message):
        read_export(setup(tmp_path))


def test_zip_without_conversations_gives_clear_error(tmp_path):
    path = tmp_path / "other.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("photos/cat.jpg", b"not really a cat")
    with pytest.raises(ImportFailed, match="Is this a ChatGPT data export"):
        read_export(path)


# --- command line ----------------------------------------------------------


def test_cli_import_then_reimport(isolated_home):
    first = runner.invoke(app, ["import", "chatgpt", str(CHATGPT_ZIP)])
    assert first.exit_code == 0, first.output
    assert "Imported 3 conversation(s) from ChatGPT: 3 new, 0 updated, 0 unchanged." in first.output
    assert "Skipped 2:" in first.output
    assert "Broken chat: missing message tree" in first.output

    again = runner.invoke(app, ["import", "chatgpt", str(CHATGPT_ZIP)])
    assert again.exit_code == 0
    assert "0 new, 0 updated, 3 unchanged." in again.output

    with Store() as store:
        assert store.path.parent == isolated_home
        assert store.count() == 3


def test_cli_bad_path_exits_with_error(tmp_path):
    result = runner.invoke(app, ["import", "chatgpt", str(tmp_path / "nope.zip")])
    assert result.exit_code == 1
    assert "Error: File not found" in result.output

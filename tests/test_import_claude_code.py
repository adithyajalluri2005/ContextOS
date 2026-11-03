from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from contextos.cli import app
from contextos.importers import ImportFailed
from contextos.importers.claude_code import (
    MAX_TOOL_ARG_CHARS,
    default_projects_dir,
    find_session_files,
    parse_session,
    read_sessions,
)
from contextos.store import Store
from fixtures.make_fixtures import (
    CLAUDE_CODE_DIR,
    IMAGE_SESSION,
    REWIND_SESSION,
    SHOP_SESSION,
    claude_code_sessions,
    write_claude_code_dir,
)

runner = CliRunner()
SHOP_FILE = CLAUDE_CODE_DIR / "D--work-shop" / f"{SHOP_SESSION}.jsonl"


@pytest.fixture(scope="module")
def parsed():
    return read_sessions(CLAUDE_CODE_DIR)


def by_id(parsed, session_id):
    return next(c for c in parsed.conversations if c.source_id == session_id)


def contents(conv):
    return [m.content for m in conv.messages]


# --- the committed test folder ---------------------------------------------


def test_committed_folder_matches_generator(tmp_path):
    rebuilt = write_claude_code_dir(tmp_path / "projects")
    for rel in claude_code_sessions():
        committed = (CLAUDE_CODE_DIR / rel).read_text(encoding="utf-8").splitlines()
        assert committed == (rebuilt / rel).read_text(encoding="utf-8").splitlines(), (
            f"{rel} is out of date; run tests/fixtures/make_fixtures.py"
        )


# --- finding sessions ------------------------------------------------------


def test_finds_sessions_but_not_subagent_files():
    names = [f.name for f in find_session_files(CLAUDE_CODE_DIR)]
    assert "agent-1.jsonl" not in names
    assert len(names) == 4


def test_accepts_one_project_folder_or_one_file():
    assert len(find_session_files(CLAUDE_CODE_DIR / "D--work-shop")) == 3
    assert find_session_files(SHOP_FILE) == [SHOP_FILE]


def test_default_folder_follows_claude_config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    assert default_projects_dir() == tmp_path / "cfg" / "projects"
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    assert default_projects_dir().parts[-2:] == (".claude", "projects")


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (lambda p: p / "missing", "Not found"),
        (lambda p: p, "No Claude Code sessions"),
        (lambda p: (p / "notes.txt").write_text("hi") and p / "notes.txt", "not a .jsonl"),
    ],
)
def test_bad_paths_give_clear_errors(tmp_path, make, message):
    with pytest.raises(ImportFailed, match=message):
        read_sessions(make(tmp_path))


def test_reads_sessions_and_skips_empty_ones(parsed):
    assert sorted(c.source_id for c in parsed.conversations) == sorted(
        [SHOP_SESSION, REWIND_SESSION, IMAGE_SESSION]
    )
    assert len(parsed.skipped) == 1
    assert parsed.skipped[0].endswith("no visible messages")


# --- what is kept ----------------------------------------------------------


def test_shop_session_messages(parsed):
    conv = by_id(parsed, SHOP_SESSION)
    roles = [m.role for m in conv.messages]
    assert roles == ["system", "user", "assistant", "user", "assistant"]
    assert conv.messages[0].content == "Working folder: D:\\work\\shop (git branch: main)"
    assert conv.messages[1].content == "Add a login page"
    assert conv.messages[3].content == "[command: /review src/login.py]"
    assert conv.messages[4].content == "The login code looks fine."


def test_tool_calls_become_short_lines_and_answers_are_joined(parsed):
    answer = by_id(parsed, SHOP_SESSION).messages[2].content
    lines = answer.split("\n\n")
    assert lines[0] == "I'll look at the routes."
    assert lines[1] == "[read file: src/routes.py]"
    assert lines[2] == "[ran: pytest -q]"
    assert lines[3].startswith("[ran: echo xxx") and lines[3].endswith("...]")
    assert len(lines[3]) <= MAX_TOOL_ARG_CHARS + len("[ran: ]")
    assert lines[4] == "[used tool: TodoWrite]"
    assert lines[5] == "Login page added. Tests pass."


def test_dropped_content_never_appears(parsed):
    everything = "\n".join(m.content for c in parsed.conversations for m in c.messages)
    for hidden in [
        "SECRET FILE CONTENT",  # tool result
        "SECRET THINKING",
        "SIDECHAIN",
        "SUBAGENT",
        "Caveat:",
        "Review started",  # command output
        "background job finished",  # task notification
        "API Error",
        "This session is being continued",  # compaction summary
    ]:
        assert hidden not in everything, hidden


def test_rewind_keeps_last_branch_and_compaction_keeps_history(parsed):
    conv = by_id(parsed, REWIND_SESSION)
    assert contents(conv)[1:] == [
        "Rename variable x to total", "Renamed.",
        "Now add a test", "Test added.",
        "[Claude Code compacted the conversation here]",
        "Continuing.", "Thanks", "You're welcome.",
    ]


def test_images_become_a_placeholder(parsed):
    conv = by_id(parsed, IMAGE_SESSION)
    assert conv.messages[1].content.endswith("\n\n[image]")
    assert conv.messages[0].content == "Working folder: D:\\other (git branch: main)"


# --- titles and dates ------------------------------------------------------


def test_title_priority(parsed):
    assert by_id(parsed, SHOP_SESSION).title == "Login page for the shop"  # newest AI title
    assert by_id(parsed, REWIND_SESSION).title == "Rename and test"  # custom title wins
    image_title = by_id(parsed, IMAGE_SESSION).title  # no title lines: first prompt, shortened
    assert image_title.startswith("What is in this screenshot?") and len(image_title) <= 80


def test_dates_cover_the_session(parsed):
    conv = by_id(parsed, SHOP_SESSION)
    assert conv.created_at == datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    assert conv.updated_at == datetime(2026, 11, 1, 10, 1, 3, tzinfo=timezone.utc)
    assert conv.source_tool == "claude-code" and conv.url is None


def test_windows_line_endings_are_fine(tmp_path):
    path = tmp_path / "crlf.jsonl"
    path.write_bytes(SHOP_FILE.read_bytes().replace(b"\n", b"\r\n"))
    assert contents(parse_session(path)) == contents(parse_session(SHOP_FILE))


# --- command line ----------------------------------------------------------


def test_cli_import_then_reimport(isolated_home):
    first = runner.invoke(app, ["import", "claude-code", "--path", str(CLAUDE_CODE_DIR)])
    assert first.exit_code == 0, first.output
    assert "Imported 3 conversation(s) from Claude Code: 3 new, 0 updated, 0 unchanged." in first.output
    assert "Skipped 1:" in first.output

    again = runner.invoke(app, ["import", "claude-code", "--path", str(CLAUDE_CODE_DIR)])
    assert "0 new, 0 updated, 3 unchanged." in again.output
    with Store() as store:
        assert store.count() == 3


def test_cli_uses_claude_config_dir_by_default(isolated_home, monkeypatch, tmp_path):
    cfg = tmp_path / "claude-config"
    write_claude_code_dir(cfg / "projects")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    result = runner.invoke(app, ["import", "claude-code"])
    assert result.exit_code == 0, result.output
    assert "3 new" in result.output


def test_cli_bad_path_exits_with_error(tmp_path):
    result = runner.invoke(app, ["import", "claude-code", "--path", str(tmp_path / "nope")])
    assert result.exit_code == 1
    assert "Error: Not found" in result.output

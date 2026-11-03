"""Builds the made-up test exports in this folder. All content is invented.

Run from the repo root to rebuild:  python tests/fixtures/make_fixtures.py
A test checks that the committed files match what this script produces.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHATGPT_ZIP = HERE / "chatgpt_export.zip"
_FIXED_ZIP_TIME = (2026, 11, 3, 0, 0, 0)

T = 1793520000.0  # base time, in seconds since 1970 (UTC)
LONG_TOOL_OUTPUT = "row ok\n" * 700  # 4900 characters, longer than the importer keeps


def _node(node_id, parent, children, role=None, content=None, t=None, hidden=False, name=None):
    message = None
    if role is not None:
        message = {
            "id": node_id,
            "author": {"role": role, "name": name, "metadata": {}},
            "create_time": t,
            "content": content,
            "metadata": {"is_visually_hidden_from_conversation": True} if hidden else {},
            "recipient": "all",
        }
    return {"id": node_id, "message": message, "parent": parent, "children": children}


def _text(*parts):
    return {"content_type": "text", "parts": list(parts)}


def chatgpt_conversations() -> list[dict]:
    trip = {
        "title": "Plan a trip to Goa",
        "create_time": T,
        "update_time": T + 600,
        "conversation_id": "aaaa1111-0000-4000-8000-000000000001",
        "id": "aaaa1111-0000-4000-8000-000000000001",
        "current_node": "a2b",
        "mapping": {
            "root": _node("root", None, ["sys"]),
            "sys": _node("sys", "root", ["u1"], "system", _text(""), None, hidden=True),
            "u1": _node("u1", "sys", ["a1"], "user", _text("Plan a 3-day trip to Goa."), T + 10),
            "a1": _node("a1", "u1", ["u2a", "u2b"], "assistant",
                        _text("Day 1: beaches. Day 2: forts. Day 3: markets."), T + 20),
            # Old branch: the user edited this message later, so it must NOT be imported.
            "u2a": _node("u2a", "a1", ["a2a"], "user", _text("Make it cheaper."), T + 30),
            "a2a": _node("a2a", "u2a", [], "assistant", _text("Budget version: hostels only."), T + 40),
            # Branch the user ended on.
            "u2b": _node("u2b", "a1", ["a2b"], "user", _text("Add a day trip to Dudhsagar falls."), T + 50),
            "a2b": _node("a2b", "u2b", [], "assistant", {
                "content_type": "multimodal_text",
                "parts": [
                    "Here is the updated plan with Dudhsagar on day 2.",
                    {"content_type": "image_asset_pointer", "asset_pointer": "file-service://file-123"},
                ],
            }, T + 60),
        },
    }

    csv = {
        "title": "CSV cleanup in Python",
        "create_time": T + 1000,
        "update_time": T + 1500,
        "conversation_id": "bbbb2222-0000-4000-8000-000000000002",
        "id": "bbbb2222-0000-4000-8000-000000000002",
        "current_node": "done",
        "mapping": {
            "root": _node("root", None, ["ctx"]),
            "ctx": _node("ctx", "root", ["u1"], "user", {
                "content_type": "user_editable_context",
                "user_profile": "I am a data analyst.",
                "user_instructions": "Answer briefly.",
            }, None, hidden=True),
            "u1": _node("u1", "ctx", ["think"], "user", _text("Remove empty rows from data.csv"), T + 1010),
            "think": _node("think", "u1", ["code"], "assistant", {
                "content_type": "thoughts",
                "thoughts": [{"summary": "Plan", "content": "Use pandas dropna."}],
            }, T + 1020),
            "code": _node("code", "think", ["out"], "assistant", {
                "content_type": "code",
                "language": "python",
                "text": "import pandas as pd\ndf = pd.read_csv('data.csv').dropna(how='all')",
            }, T + 1030),
            "out": _node("out", "code", ["done"], "tool", {
                "content_type": "execution_output",
                "text": LONG_TOOL_OUTPUT,
            }, T + 1040, name="python"),
            "done": _node("done", "out", [], "assistant", _text("Done. 12 empty rows removed."), T + 1050),
        },
    }

    no_current = {
        "title": "No current node",
        "create_time": T + 2000,
        "update_time": None,
        "conversation_id": "cccc3333-0000-4000-8000-000000000003",
        "current_node": None,
        "mapping": {
            "root": _node("root", None, ["u1"]),
            "u1": _node("u1", "root", ["old", "new"], "user", _text("Name ideas for a cat?"), T + 2010),
            "old": _node("old", "u1", [], "assistant", _text("Whiskers."), T + 2020),
            "new": _node("new", "u1", [], "assistant", _text("Mango."), T + 2030),
        },
    }

    only_hidden = {
        "title": "Only hidden messages",
        "create_time": T + 3000,
        "conversation_id": "eeee5555-0000-4000-8000-000000000005",
        "current_node": "sys",
        "mapping": {
            "root": _node("root", None, ["sys"]),
            "sys": _node("sys", "root", [], "system", _text(""), None, hidden=True),
        },
    }

    broken = {"title": "Broken chat", "id": "dddd4444-0000-4000-8000-000000000004"}

    return [trip, csv, no_current, only_hidden, broken]


def write_chatgpt_zip(path: Path = CHATGPT_ZIP) -> Path:
    """Write a ZIP shaped like a real export: conversations.json plus other files to ignore."""
    files = {
        "conversations.json": json.dumps(chatgpt_conversations(), indent=1),
        # These exist in real exports and must be ignored by the importer.
        "shared_conversations.json": json.dumps([{"id": "s1", "conversation_id": "x", "title": "Shared"}]),
        "user.json": json.dumps({"id": "user-test", "email": "test@example.com"}),
        "chat.html": "<html><body>made-up export</body></html>",
    }
    _write_zip(path, files)
    return path


# --- Claude.ai -------------------------------------------------------------

CLAUDE_ZIP = HERE / "claude_export.zip"
CLAUDE_ROOT = "00000000-0000-4000-8000-000000000000"
LONG_ATTACHMENT = "Requirement line.\n" * 300  # 5400 characters, longer than the importer keeps


def _cmsg(uuid, sender, when, *, parent=None, text="", content=None, attachments=None, files=None):
    msg = {
        "uuid": uuid,
        "text": text,
        "sender": sender,
        "created_at": when,
        "updated_at": when,
        "attachments": attachments or [],
        "files": files or [],
    }
    if content is not None:
        msg["content"] = content
    if parent is not None:
        msg["parent_message_uuid"] = parent
    return msg


def _ctext(text):
    return {"type": "text", "text": text, "start_timestamp": None, "stop_timestamp": None, "citations": []}


def claude_conversations() -> list[dict]:
    db_choice = {
        "uuid": "11111111-aaaa-4000-8000-000000000001",
        "name": "Database choice for ContextOS",
        "created_at": "2026-11-01T10:00:00.000000Z",
        "updated_at": "2026-11-01T10:05:00.000000Z",
        "account": {"uuid": "acct-test"},
        "chat_messages": [
            _cmsg("m1", "human", "2026-11-01T10:00:00.000000Z", parent=CLAUDE_ROOT,
                  text="Should I use SQLite or Postgres? Requirements attached.",
                  content=[_ctext("Should I use SQLite or Postgres? Requirements attached.")],
                  attachments=[{"file_name": "requirements.txt", "file_size": 5400,
                                "file_type": "txt", "extracted_content": LONG_ATTACHMENT}],
                  files=[{"file_name": "diagram.png"}]),
            _cmsg("m2", "assistant", "2026-11-01T10:01:00.000000Z", parent="m1",
                  text="Use SQLite for the local tool.",
                  content=[
                      {"type": "thinking", "thinking": "SECRET REASONING: weigh both options."},
                      {"type": "tool_use", "name": "web_search", "input": {"query": "sqlite limits"}},
                      {"type": "tool_result", "name": "web_search",
                       "content": [{"type": "text", "text": "RAW SEARCH RESULT"}], "is_error": False},
                      _ctext("Use SQLite for the local tool."),
                      _ctext("Move to Postgres only for the team server."),
                  ]),
        ],
    }

    branched = {
        "uuid": "22222222-bbbb-4000-8000-000000000002",
        "name": "Name for the project",
        "created_at": "2026-11-02T09:00:00Z",
        "updated_at": "2026-11-02T09:10:00Z",
        "chat_messages": [
            _cmsg("b1", "human", "2026-11-02T09:00:00Z", parent=CLAUDE_ROOT, text="Suggest a name.",
                  content=[_ctext("Suggest a name.")]),
            _cmsg("b2", "assistant", "2026-11-02T09:01:00Z", parent="b1", text="ContextOS.",
                  content=[_ctext("ContextOS.")]),
            # Old branch: the user edited this message later, so it must NOT be imported.
            _cmsg("b3", "human", "2026-11-02T09:02:00Z", parent="b2", text="Something shorter?",
                  content=[_ctext("Something shorter?")]),
            _cmsg("b4", "assistant", "2026-11-02T09:03:00Z", parent="b3", text="Ctx.",
                  content=[_ctext("Ctx.")]),
            # Branch the user ended on.
            _cmsg("b5", "human", "2026-11-02T09:05:00Z", parent="b2", text="Something friendlier?",
                  content=[_ctext("Something friendlier?")]),
            _cmsg("b6", "assistant", "2026-11-02T09:06:00Z", parent="b5", text="Carry.",
                  content=[_ctext("Carry.")]),
        ],
    }

    # Older export style: no parent links, no content blocks, empty name, dates without time zone.
    older = {
        "uuid": "33333333-cccc-4000-8000-000000000003",
        "name": "",
        "created_at": "2026-10-20T08:00:00",
        "updated_at": "2026-10-20T08:01:00",
        "chat_messages": [
            _cmsg("o1", "human", "2026-10-20T08:00:00", text="Hello"),
            _cmsg("o2", "assistant", "2026-10-20T08:01:00", text="Hi! How can I help?"),
        ],
    }

    empty = {
        "uuid": "44444444-dddd-4000-8000-000000000004",
        "name": "Empty chat",
        "created_at": "2026-11-03T00:00:00Z",
        "updated_at": "2026-11-03T00:00:00Z",
        "chat_messages": [],
    }

    no_id = {"name": "Chat without id", "chat_messages": []}

    return [db_choice, branched, older, empty, no_id]


def write_claude_zip(path: Path = CLAUDE_ZIP) -> Path:
    """Write a ZIP shaped like a real Claude export: conversations.json plus files to ignore."""
    files = {
        "conversations.json": json.dumps(claude_conversations(), indent=1),
        "users.json": json.dumps([{"uuid": "acct-test", "full_name": "Test User",
                                   "email_address": "test@example.com"}]),
        "projects.json": json.dumps([{"uuid": "p1", "name": "Test project", "docs": []}]),
    }
    _write_zip(path, files)
    return path


def _write_zip(path: Path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, text in files.items():
            info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, text)


if __name__ == "__main__":
    print(f"wrote {write_chatgpt_zip()}")
    print(f"wrote {write_claude_zip()}")

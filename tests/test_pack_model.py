import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from contextos.cli import app
from contextos.pack import SPEC_VERSION, ContextPack, json_schema

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMITTED_SCHEMA = REPO_ROOT / "schemas" / "context-pack.schema.json"

runner = CliRunner()


def minimal_data() -> dict:
    return {
        "title": "Build plan for ContextOS",
        "summary": "We planned a tool that moves AI chats between tools.",
        "source": {"tool": "chatgpt"},
    }


def full_data() -> dict:
    return {
        "title": "Build plan for ContextOS",
        "summary": "We planned a tool that moves AI chats between tools.",
        "decisions": [
            {"decision": "Start with a command-line tool", "reason": "Proves the idea with no server"},
            {"decision": "Use SQLite locally"},
        ],
        "open_questions": ["Which browser should the extension support first?"],
        "next_steps": ["Write the ChatGPT importer"],
        "key_facts": ["Python 3.12", "License is MIT"],
        "code_snippets": [
            {"code": "contextos pack 42 --out context.md", "language": "shell", "description": "Make a pack"}
        ],
        "file_refs": [{"path": "contextos/cli.py", "description": "Command entry point"}],
        "source": {
            "tool": "claude-ai",
            "conversation_id": "abc-123",
            "title": "ContextOS planning",
            "url": "https://claude.ai/chat/abc-123",
            "created_at": "2026-11-01T10:00:00Z",
            "updated_at": "2026-11-03T12:30:00+05:30",
        },
        "created_at": "2026-11-03T08:00:00Z",
        "raw_transcript": [
            {"role": "user", "content": "How do I move my chat?", "created_at": "2026-11-01T10:00:00Z"},
            {"role": "assistant", "content": "Export it, then make a pack."},
        ],
    }


# --- model -----------------------------------------------------------------


def test_minimal_pack_gets_defaults():
    pack = ContextPack.model_validate(minimal_data())
    assert pack.spec_version == SPEC_VERSION == "0.1"
    assert pack.decisions == [] and pack.next_steps == [] and pack.key_facts == []
    assert pack.raw_transcript is None
    assert pack.created_at.tzinfo is not None


def test_full_pack_round_trips_through_json():
    pack = ContextPack.model_validate(full_data())
    again = ContextPack.from_json(pack.to_json())
    assert again == pack
    assert again.decisions[0].reason == "Proves the idea with no server"
    assert again.source.updated_at == datetime(2026, 11, 3, 7, 0, tzinfo=timezone.utc)


def test_to_json_leaves_out_empty_optional_values():
    out = json.loads(ContextPack.model_validate(minimal_data()).to_json())
    assert "raw_transcript" not in out
    assert "url" not in out["source"]


def test_text_is_trimmed():
    data = minimal_data() | {"title": "  Spaced title  "}
    assert ContextPack.model_validate(data).title == "Spaced title"


@pytest.mark.parametrize("field", ["title", "summary", "source"])
def test_required_fields(field):
    data = minimal_data()
    del data[field]
    with pytest.raises(ValidationError):
        ContextPack.model_validate(data)


@pytest.mark.parametrize("field", ["title", "summary"])
def test_blank_text_is_rejected(field):
    with pytest.raises(ValidationError):
        ContextPack.model_validate(minimal_data() | {field: "   "})


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        ContextPack.model_validate(minimal_data() | {"sumary": "typo"})


def test_unknown_nested_field_is_rejected():
    data = minimal_data() | {"decisions": [{"decision": "x", "because": "typo"}]}
    with pytest.raises(ValidationError):
        ContextPack.model_validate(data)


def test_other_spec_version_is_rejected():
    with pytest.raises(ValidationError):
        ContextPack.model_validate(minimal_data() | {"spec_version": "9.0"})


def test_date_without_timezone_is_rejected():
    data = minimal_data() | {"source": {"tool": "chatgpt", "created_at": "2026-11-01T10:00:00"}}
    with pytest.raises(ValidationError):
        ContextPack.model_validate(data)


def test_unknown_message_role_is_rejected():
    data = minimal_data() | {"raw_transcript": [{"role": "robot", "content": "hi"}]}
    with pytest.raises(ValidationError):
        ContextPack.model_validate(data)


def test_decision_needs_text():
    data = minimal_data() | {"decisions": [{"reason": "no decision text"}]}
    with pytest.raises(ValidationError):
        ContextPack.model_validate(data)


# --- schema ----------------------------------------------------------------


def test_schema_has_header_and_required_fields():
    schema = json_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == "context-pack.schema.json"
    assert schema["title"] == "ContextPack"
    assert set(schema["required"]) == {"title", "summary", "source"}
    for field in ["decisions", "open_questions", "next_steps", "key_facts", "code_snippets",
                  "file_refs", "raw_transcript", "spec_version", "created_at"]:
        assert field in schema["properties"]


def test_schema_command_writes_file(tmp_path):
    out = tmp_path / "nested" / "pack.schema.json"
    result = runner.invoke(app, ["schema", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert json.loads(out.read_text(encoding="utf-8")) == json_schema()
    assert b"\r\n" not in out.read_bytes()


def test_schema_command_prints_when_no_file_given():
    result = runner.invoke(app, ["schema"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == json_schema()


def test_committed_schema_file_is_up_to_date():
    assert COMMITTED_SCHEMA.exists(), "run: contextos schema --out schemas/context-pack.schema.json"
    committed = json.loads(COMMITTED_SCHEMA.read_text(encoding="utf-8"))
    assert committed == json_schema(), "schema is out of date; run: contextos schema --out schemas/context-pack.schema.json"

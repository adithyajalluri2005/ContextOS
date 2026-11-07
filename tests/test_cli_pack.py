import json

import pytest
from typer.testing import CliRunner

import contextos.cli as cli
from contextos.cli import app
from contextos.llm import FakeProvider, ProviderError
from contextos.pack import ContextPack, Message
from contextos.pack.render import CLAUDE_MD_START
from contextos.store import ConversationIn, Store
from fixtures.make_fixtures import CHATGPT_ZIP

runner = CliRunner()

DRAFT = {
    "title": "Speed up a slow SQL query",
    "summary": "The report was slow; an index fixed it.",
    "decisions": [{"decision": "Add an index on orders.customer_id", "reason": "The join scanned every row"}],
    "open_questions": [],
    "next_steps": ["Check the live database"],
    "key_facts": [],
    "code_snippets": [],
    "file_refs": [],
}


@pytest.fixture
def fake(monkeypatch):
    """Replace the provider picked from the environment with a FakeProvider that gives DRAFT."""
    provider = FakeProvider(lambda system, prompt: DRAFT)
    monkeypatch.setattr(cli, "get_provider", lambda: provider)
    return provider


@pytest.fixture
def conv_id():
    with Store() as store:
        conv_id, _ = store.save(
            ConversationIn(
                source_tool="claude-ai",
                source_id="cl-1",
                title="Slow join",
                messages=[
                    Message(role="user", content="My join is slow."),
                    Message(role="assistant", content="Add an index on orders.customer_id."),
                ],
            )
        )
    return conv_id


def run(*args: str):
    return runner.invoke(app, list(args))


def test_pack_writes_markdown_file(tmp_path, fake, conv_id):
    out = tmp_path / "ctx" / "context.md"
    result = run("pack", str(conv_id), "--out", str(out))
    assert result.exit_code == 0, result.output
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# Context: Speed up a slow SQL query\n")
    assert "- Add an index on orders.customer_id (reason: The join scanned every row)" in text
    assert "_From Claude.ai, conversation \"Slow join\"._" in text
    assert b"\r\n" not in out.read_bytes()
    assert f"Wrote {out}" in result.stderr
    # The model saw the chat text.
    assert "My join is slow." in fake.calls[0].prompt


def test_pack_prints_to_screen_without_out(fake, conv_id):
    result = run("pack", str(conv_id))
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("# Context: Speed up a slow SQL query")
    # Progress goes to stderr, so the printed pack can be piped into a file cleanly.
    assert "Building the pack with fake" in result.stderr
    assert "Building" not in result.stdout


def test_pack_json_format(fake, conv_id):
    result = run("pack", str(conv_id), "--format", "json")
    assert result.exit_code == 0, result.output
    pack = ContextPack.from_json(result.stdout)
    assert pack.title == "Speed up a slow SQL query"
    assert pack.source.tool == "claude-ai"
    assert pack.source.conversation_id == "cl-1"
    assert pack.raw_transcript is None


def test_pack_claude_md_format(tmp_path, fake, conv_id):
    out = tmp_path / "section.md"
    result = run("pack", str(conv_id), "-f", "claude-md", "-o", str(out))
    assert result.exit_code == 0, result.output
    text = out.read_text(encoding="utf-8")
    assert text.startswith(CLAUDE_MD_START)
    assert "### Decisions" in text


def test_pack_with_transcript(fake, conv_id):
    result = run("pack", str(conv_id), "--format", "json", "--with-transcript")
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert [m["content"] for m in data["raw_transcript"]] == ["My join is slow.", "Add an index on orders.customer_id."]


def test_pack_unknown_format(fake, conv_id):
    result = run("pack", str(conv_id), "--format", "html")
    assert result.exit_code == 2
    assert "unknown format 'html'" in result.stderr
    assert fake.calls == []


def test_pack_unknown_id(fake):
    result = run("pack", "9999")
    assert result.exit_code == 1
    assert "no conversation with ID 9999" in result.stderr


def test_pack_empty_conversation_fails_cleanly(fake):
    with Store() as store:
        empty_id, _ = store.save(ConversationIn(source_tool="chatgpt", source_id="empty", title="Empty"))
    result = run("pack", str(empty_id))
    assert result.exit_code == 1
    assert "no messages" in result.stderr


def test_pack_without_provider_set_explains_what_to_do(monkeypatch, conv_id):
    monkeypatch.delenv("CONTEXTOS_PROVIDER", raising=False)
    result = run("pack", str(conv_id))
    assert result.exit_code == 1
    assert "CONTEXTOS_PROVIDER" in result.stderr


def test_pack_provider_error_is_reported(monkeypatch, conv_id):
    def broken():
        raise ProviderError("ANTHROPIC_API_KEY is not set.")

    monkeypatch.setattr(cli, "get_provider", broken)
    result = run("pack", str(conv_id))
    assert result.exit_code == 1
    assert "Error: ANTHROPIC_API_KEY is not set." in result.stderr


def test_pack_uses_fake_provider_from_environment(monkeypatch, conv_id):
    monkeypatch.setenv("CONTEXTOS_PROVIDER", "fake")
    result = run("pack", str(conv_id))
    assert result.exit_code == 0, result.output
    # The fake default answer has its own title; the original chat is still named as the source.
    assert result.stdout.startswith("# Context: Conversation summary")
    assert '"Slow join"' in result.stdout


def test_pack_after_real_fixture_import(monkeypatch):
    monkeypatch.setenv("CONTEXTOS_PROVIDER", "fake")
    assert run("import", "chatgpt", str(CHATGPT_ZIP)).exit_code == 0
    with Store() as store:
        first = store.list_conversations("chatgpt")[0]
    result = run("pack", str(first.id), "--format", "json")
    assert result.exit_code == 0, result.output
    assert ContextPack.from_json(result.stdout).source.tool == "chatgpt"

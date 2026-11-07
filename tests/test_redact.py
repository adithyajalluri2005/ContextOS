"""Secret hiding. Every secret here is made up, and built from pieces so that
secret scanners do not mistake this file for a leak."""

import json
from collections import Counter

import pytest
from typer.testing import CliRunner

import contextos.cli as cli
from contextos.cli import app
from contextos.llm import FakeProvider
from contextos.pack import ContextPack, Message, render
from contextos.pack.model import Source
from contextos.redact import (
    ANTHROPIC_KEY,
    AWS_KEY,
    EMAIL,
    GITHUB_TOKEN,
    OPENAI_KEY,
    PHONE,
    PRIVATE_KEY,
    URL_PASSWORD,
    marker,
    ordered,
    redact_model,
    redact_text,
)
from contextos.store import ConversationIn, Store

OPENAI = "sk-" + "proj-" + "Ab3dEf6hIj9kLm2nOp5qRs8tUv"
OPENAI_OLD = "sk-" + "Zy1xWv4uTs7rQp0oNm3lKj6iHg"
ANTHROPIC = "sk-" + "ant-" + "api03-" + "Qw2eRt5yUi8oPa1sDf4gHj7kL"
AWS_ID = "AKIA" + "IOSFODNN7" + "EXAMPLE"
AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/" + "bPxRfiCYEXAMPLEKEY"
GITHUB = "ghp_" + "1a2B3c4D5e6F7g8H9i0J" + "1k2L3m4N5o6P7q8R"
GITHUB_PAT = "github_pat_" + "11ABCDEFG0" + "a" * 50
PEM = "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA1b2c3d4\nZm9vYmFy\n-----END RSA " + "PRIVATE KEY-----"
SECRETS = [OPENAI, OPENAI_OLD, ANTHROPIC, AWS_ID, AWS_SECRET, GITHUB, GITHUB_PAT, "hunter2pass", "riya@example.com"]


def hide(text: str) -> tuple[str, dict[str, int]]:
    counts: Counter[str] = Counter()
    return redact_text(text, counts), ordered(counts)


# --- each kind ---------------------------------------------------------------


@pytest.mark.parametrize(
    "secret, kind",
    [
        (OPENAI, OPENAI_KEY),
        (OPENAI_OLD, OPENAI_KEY),
        (ANTHROPIC, ANTHROPIC_KEY),
        (AWS_ID, AWS_KEY),
        (GITHUB, GITHUB_TOKEN),
        (GITHUB_PAT, GITHUB_TOKEN),
        (PEM, PRIVATE_KEY),
        ("riya.k+work@mail.example.co.in", EMAIL),
        ("+91 98765 43210", PHONE),
        ("(555) 123-4567", PHONE),
        ("555-123-4567", PHONE),
        ("+14155550123", PHONE),
    ],
)
def test_each_kind_is_hidden(secret, kind):
    text, counts = hide(f"Here it is: {secret} - use it.")
    assert secret not in text
    assert text == f"Here it is: {marker(kind)} - use it."
    assert counts == {kind: 1}


def test_anthropic_key_is_not_counted_as_openai():
    _, counts = hide(ANTHROPIC)
    assert counts == {ANTHROPIC_KEY: 1}


def test_aws_secret_keeps_the_setting_name():
    text, counts = hide(f"aws_secret_access_key = {AWS_SECRET}\nAWS_SECRET_ACCESS_KEY: '{AWS_SECRET}'")
    assert AWS_SECRET not in text
    assert text == f"aws_secret_access_key = {marker(AWS_KEY)}\nAWS_SECRET_ACCESS_KEY: '{marker(AWS_KEY)}'"
    assert counts == {AWS_KEY: 2}


def test_url_password_hides_only_the_password():
    text, counts = hide("Connect to postgres://admin:hunter2pass@db.example.com:5432/shop now")
    assert "hunter2pass" not in text
    assert f"postgres://admin:{marker(URL_PASSWORD)}@db.example.com:5432/shop" in text
    assert counts == {URL_PASSWORD: 1}


def test_private_key_block_is_hidden_whole():
    text, counts = hide(f"key:\n{PEM}\nend")
    assert text == f"key:\n{marker(PRIVATE_KEY)}\nend"
    assert counts == {PRIVATE_KEY: 1}
    openssh = "-----BEGIN OPENSSH " + "PRIVATE KEY-----\nb3BlbnNzaA==\n-----END OPENSSH " + "PRIVATE KEY-----"
    assert hide(openssh)[1] == {PRIVATE_KEY: 1}


def test_counts_add_up_over_many_items():
    text, counts = hide(f"{OPENAI} a@b.io {OPENAI_OLD} c@d.io e@f.io")
    assert counts == {OPENAI_KEY: 2, EMAIL: 3}
    assert text.count("[hidden:") == 5


# --- things that must stay ---------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Released on 2026-03-01 and 01/03/2026.",
        "Version 3.12.4 and build 20260301.",
        "Server at 192.168.100.200 port 8080.",
        "Order 1234567890123 shipped.",
        "It costs 4,000,000 rupees.",
        "https://example.com/docs?page=2",
        "Run `pip install sk-learn` (not a key).",
        "user@localhost is not a full address",
        "The ticket is ABC-1234.",
        "From 9 to 5, 2 to 3 times a week.",
    ],
)
def test_normal_text_is_kept(text):
    assert hide(text) == (text, {})


def test_text_without_secrets_is_unchanged_and_counts_nothing():
    counts: Counter[str] = Counter()
    assert redact_text("Plan two days in Pune.", counts) == "Plan two days in Pune."
    assert not counts


# --- models ------------------------------------------------------------------


def test_redact_model_cleans_every_text_field():
    pack = ContextPack(
        title="Keys for riya@example.com",
        summary=f"Use {OPENAI}.",
        key_facts=[f"AWS id {AWS_ID}"],
        source=Source(tool="chatgpt", url="https://bob:hunter2pass@example.com/c/1"),
        raw_transcript=[Message(role="user", content=f"my token {GITHUB}")],
    )
    counts: Counter[str] = Counter()
    clean = redact_model(pack, counts)
    text = clean.to_json()
    for secret in SECRETS:
        assert secret not in text
    assert ordered(counts) == {URL_PASSWORD: 1, OPENAI_KEY: 1, AWS_KEY: 1, GITHUB_TOKEN: 1, EMAIL: 1}
    assert clean.created_at == pack.created_at
    assert pack.summary == f"Use {OPENAI}."  # the original is not changed


def test_rendered_pack_shows_only_counts():
    pack = ContextPack(title="T", summary="S", source=Source(tool="chatgpt"), redacted={EMAIL: 2, OPENAI_KEY: 1})
    md = render(pack, "markdown")
    assert "_3 items were hidden for privacy (email: 2, OpenAI key: 1)._" in md
    assert "hidden for privacy" in render(pack, "claude-md")
    assert json.loads(render(pack, "json"))["redacted"] == {"email": 2, "OpenAI key": 1}
    one = pack.model_copy(update={"redacted": {EMAIL: 1}})
    assert "_1 item was hidden for privacy (email: 1)._" in render(one, "markdown")
    nothing = pack.model_copy(update={"redacted": {}})
    assert "hidden for privacy" not in render(nothing, "markdown")


# --- the pack command --------------------------------------------------------

runner = CliRunner()


@pytest.fixture
def leaky_id():
    with Store() as store:
        conv_id, _ = store.save(
            ConversationIn(
                source_tool="chatgpt",
                source_id="leak-1",
                title="Deploy help for riya@example.com",
                url="https://chatgpt.com/c/leak-1",
                messages=[
                    Message(role="user", content=f"My key is {OPENAI} and the db is postgres://admin:hunter2pass@db.example.com/shop"),
                    Message(role="assistant", content=f"Do not share {OPENAI}. Call +91 98765 43210 for help."),
                ],
            )
        )
    return conv_id


@pytest.fixture
def echo_provider(monkeypatch):
    """A fake model that copies the chat it was sent into the summary, to show what it saw."""
    provider = FakeProvider(
        lambda system, prompt: {
            "title": "Deploy help",
            "summary": prompt[-1500:],
            "decisions": [],
            "open_questions": [],
            "next_steps": [],
            "key_facts": [],
            "code_snippets": [],
            "file_refs": [],
        }
    )
    monkeypatch.setattr(cli, "get_provider", lambda: provider)
    return provider


def test_pack_hides_secrets_by_default(tmp_path, echo_provider, leaky_id):
    out = tmp_path / "pack.json"
    result = runner.invoke(app, ["pack", str(leaky_id), "-f", "json", "--with-transcript", "-o", str(out)])
    assert result.exit_code == 0, result.output
    # The model never saw the secrets.
    sent = echo_provider.calls[0].prompt
    for secret in (OPENAI, "hunter2pass", "98765 43210"):
        assert secret not in sent
    assert marker(OPENAI_KEY) in sent

    text = out.read_text(encoding="utf-8")
    for secret in (OPENAI, "hunter2pass", "riya@example.com", "98765 43210"):
        assert secret not in text
        assert secret not in result.output
    pack = ContextPack.from_json(text)
    # Counted once each in the chat (title, two messages); the second pass finds nothing new.
    assert pack.redacted == {URL_PASSWORD: 1, OPENAI_KEY: 2, EMAIL: 1, PHONE: 1}
    assert pack.source.title == f"Deploy help for {marker(EMAIL)}"
    assert "Hid 5 item(s) for privacy." in result.stderr
    assert "Warning" not in result.stderr


def test_pack_with_nothing_to_hide_records_empty_counts(echo_provider):
    with Store() as store:
        conv_id, _ = store.save(
            ConversationIn(source_tool="chatgpt", source_id="ok", messages=[Message(role="user", content="Hello there.")])
        )
    result = runner.invoke(app, ["pack", str(conv_id), "-f", "json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["redacted"] == {}


def test_no_redact_keeps_text_and_warns(echo_provider, leaky_id):
    result = runner.invoke(app, ["pack", str(leaky_id), "-f", "json", "--no-redact"])
    assert result.exit_code == 0, result.output
    assert "Warning: hiding is off" in result.stderr
    assert OPENAI in echo_provider.calls[0].prompt
    data = json.loads(result.stdout)
    assert "redacted" not in data
    assert OPENAI in data["summary"]

"""Secret hiding. Every secret here is made up, and built from pieces so that
secret scanners do not mistake this file for a leak."""

from collections import Counter

import pytest

from contextos.context import CodeSnippet, Context, FileRef
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
    redact_context,
    redact_text,
)

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


# --- whole contexts ----------------------------------------------------------


def leaky_context() -> Context:
    return Context(
        id="7",
        title="Keys for riya@example.com",
        summary=f"Use {OPENAI}.",
        decisions=[f"Store {AWS_ID} in the vault"],
        key_facts=["DB is postgres://admin:hunter2pass@db.example.com/shop"],
        files=[FileRef(path="deploy.sh", note=f"has {GITHUB} in it")],
        code=[CodeSnippet(content=f"export KEY={ANTHROPIC}", language="bash")],
        source_tool="claude-code",
    )


def test_redact_context_cleans_every_text_field():
    ctx = leaky_context()
    clean = redact_context(ctx)
    text = clean.model_dump_json()
    for secret in SECRETS:
        assert secret not in text
    assert clean.redacted == {
        URL_PASSWORD: 1,
        ANTHROPIC_KEY: 1,
        OPENAI_KEY: 1,
        AWS_KEY: 1,
        GITHUB_TOKEN: 1,
        EMAIL: 1,
    }
    assert clean.title == f"Keys for {marker(EMAIL)}"
    assert clean.code[0].content == f"export KEY={marker(ANTHROPIC_KEY)}"


def test_redact_context_keeps_id_time_and_original():
    ctx = leaky_context()
    clean = redact_context(ctx)
    assert clean.id == "7"
    assert clean.created_at == ctx.created_at
    assert clean.source_tool == "claude-code"
    assert ctx.summary == f"Use {OPENAI}."  # the original is not changed
    assert ctx.redacted is None


def test_clean_context_gets_empty_counts():
    clean = redact_context(Context(title="Plan", summary="Two days in Pune."))
    assert clean.redacted == {}
    assert clean.summary == "Two days in Pune."


def test_cleaning_twice_keeps_the_counts():
    once = redact_context(leaky_context())
    twice = redact_context(once)
    assert twice == once


def test_markdown_shows_counts_but_never_secrets():
    md = redact_context(leaky_context()).to_markdown()
    for secret in SECRETS:
        assert secret not in md
    assert "> Hidden for safety: 1 password in URL, 1 Anthropic key," in md
    assert "Ask the user if you need the real value." in md


def test_markdown_has_no_hidden_note_when_nothing_was_hidden():
    for redacted in (None, {}):
        md = Context(title="T", summary="S", redacted=redacted).to_markdown()
        assert "Hidden for safety" not in md

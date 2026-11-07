"""The whole flow, as a new user runs it: import an export, list it, make a pack.

Uses the made-up ChatGPT export in tests/fixtures and the FakeProvider, so no AI
service is ever called.
"""

import os
import subprocess
import sys

from typer.testing import CliRunner

import contextos.cli as cli
from contextos.cli import app
from contextos.llm import FakeProvider
from fixtures.make_fixtures import CHATGPT_ZIP

runner = CliRunner()


def run(*args: str):
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result


def id_of(list_output: str, title: str) -> str:
    for line in list_output.splitlines():
        if line.rstrip().endswith(title):
            return line.split()[0]
    raise AssertionError(f"{title!r} not in list:\n{list_output}")


def goa_draft(system: str, prompt: str) -> dict:
    """A fake model answer built from what the model was sent, so the test can see the right chat went in."""
    assert "Dudhsagar" in prompt, "the branch the user ended on must be sent"
    assert "hostels only" not in prompt, "the edited-away branch must not be sent"
    return {
        "title": "Goa trip plan",
        "summary": "A 3-day Goa trip: beaches, then a day trip to Dudhsagar falls, then markets.",
        "decisions": [{"decision": "Visit Dudhsagar falls on day 2", "reason": "The user asked for it"}],
        "open_questions": ["Which month is best for the falls?"],
        "next_steps": ["Book a jeep to Dudhsagar"],
        "key_facts": ["The trip is 3 days long"],
        "code_snippets": [],
        "file_refs": [],
    }


def test_import_list_pack_markdown(tmp_path, monkeypatch):
    provider = FakeProvider(goa_draft)
    monkeypatch.setattr(cli, "get_provider", lambda: provider)

    imported = run("import", "chatgpt", str(CHATGPT_ZIP))
    assert "conversation(s) from ChatGPT" in imported.output

    listed = run("list")
    conv_id = id_of(listed.output, "Plan a trip to Goa")

    out = tmp_path / "context.md"
    packed = run("pack", conv_id, "--out", str(out))
    assert f"Wrote {out}" in packed.stderr
    assert len(provider.calls) == 1  # a short chat needs one request

    md = out.read_text(encoding="utf-8")
    assert md.startswith("# Context: Goa trip plan\n")
    assert "continue the work" in md
    assert '_From ChatGPT, conversation "Plan a trip to Goa"' in md
    assert "## Summary\n\nA 3-day Goa trip: beaches, then a day trip to Dudhsagar falls, then markets." in md
    assert "## Decisions\n\n- Visit Dudhsagar falls on day 2 (reason: The user asked for it)" in md
    assert "## Open questions\n\n- Which month is best for the falls?" in md
    assert "## Next steps\n\n- Book a jeep to Dudhsagar" in md
    assert "## Key facts\n\n- The trip is 3 days long" in md
    # Empty sections stay out, and the fixture holds nothing to hide.
    assert "## Code" not in md and "## Files" not in md
    assert "hidden for privacy" not in md


def test_import_twice_then_pack_every_format(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTEXTOS_PROVIDER", "fake")
    run("import", "chatgpt", str(CHATGPT_ZIP))
    again = run("import", "chatgpt", str(CHATGPT_ZIP))
    assert "0 new" in again.output

    conv_id = id_of(run("list").output, "CSV cleanup in Python")
    for fmt, start in (("markdown", "# Context:"), ("json", "{"), ("claude-md", "<!-- contextos:start -->")):
        out = tmp_path / f"pack-{fmt}"
        run("pack", conv_id, "-f", fmt, "-o", str(out))
        assert out.read_text(encoding="utf-8").startswith(start)


def test_demo_as_separate_process(tmp_path):
    """The README demo, run the way a user runs it: as its own program, settings from the environment."""
    env = {**os.environ, "CONTEXTOS_HOME": str(tmp_path / "home"), "CONTEXTOS_PROVIDER": "fake"}
    env.pop("CONTEXTOS_MODEL", None)

    def contextos(*args: str) -> subprocess.CompletedProcess:
        done = subprocess.run(
            [sys.executable, "-m", "contextos", *args],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        assert done.returncode == 0, done.stderr
        return done

    contextos("import", "chatgpt", str(CHATGPT_ZIP))
    conv_id = id_of(contextos("list").stdout, "Plan a trip to Goa")
    out = tmp_path / "context.md"
    contextos("pack", conv_id, "--out", str(out))
    md = out.read_text(encoding="utf-8")
    assert md.startswith("# Context: Conversation summary\n")  # the fake provider's default title
    assert '"Plan a trip to Goa"' in md

"""Tests for the context format. All data here is made up."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from contextos.context import CodeSnippet, Context, FileRef

FIXED_TIME = datetime(2026, 11, 9, 14, 30, tzinfo=UTC)


def full_context() -> Context:
    return Context(
        title="Move blog to static site",
        summary="We are moving a small blog from WordPress to a static site generator.",
        decisions=["Use Hugo", "Keep old URLs with redirects"],
        open_questions=["Where to host images?"],
        next_steps=["Write the redirect file", "Test the build"],
        key_facts=["About 120 posts"],
        files=[FileRef(path="config.toml", note="site settings"), FileRef(path="redirects.txt")],
        code=[CodeSnippet(content="hugo --minify", language="bash", note="Build command")],
        source_tool="claude-code",
        project_dir="D:/blog",
        created_at=FIXED_TIME,
    )


def test_only_title_and_summary_are_required():
    ctx = Context(title="T", summary="S")
    assert ctx.decisions == [] and ctx.files == [] and ctx.id is None
    assert ctx.created_at.tzinfo is not None


@pytest.mark.parametrize("field", ["title", "summary"])
def test_empty_title_or_summary_is_refused(field):
    data = {"title": "T", "summary": "S", field: "   "}
    with pytest.raises(ValidationError):
        Context(**data)


def test_title_too_long_is_refused():
    with pytest.raises(ValidationError):
        Context(title="x" * 201, summary="S")


def test_unknown_field_is_refused():
    with pytest.raises(ValidationError):
        Context(title="T", summary="S", mood="happy")


def test_text_and_list_items_are_cleaned():
    ctx = Context(title="  T  ", summary=" S ", decisions=[" a ", "", "   ", "b"])
    assert ctx.title == "T"
    assert ctx.summary == "S"
    assert ctx.decisions == ["a", "b"]


def test_time_is_stored_in_utc():
    plus_two = timezone(timedelta(hours=2))
    ctx = Context(title="T", summary="S", created_at=datetime(2026, 11, 9, 16, 30, tzinfo=plus_two))
    assert ctx.created_at == FIXED_TIME
    naive = Context(title="T", summary="S", created_at=datetime(2026, 11, 9, 14, 30))
    assert naive.created_at == FIXED_TIME


def test_json_round_trip_keeps_everything():
    ctx = full_context()
    again = Context.model_validate_json(ctx.model_dump_json())
    assert again == ctx


def test_markdown_has_every_section():
    md = full_context().to_markdown()
    assert md.startswith("# Move blog to static site\n")
    assert "Saved 2026-11-09 14:30 UTC from claude-code in `D:/blog`." in md
    for heading in ["Summary", "Decisions", "Open questions", "Next steps", "Key facts", "Files", "Code"]:
        assert f"## {heading}\n" in md
    assert "- Use Hugo\n" in md
    assert "- `config.toml`: site settings\n" in md
    assert "- `redirects.txt`\n" in md
    assert "```bash\nhugo --minify\n```" in md
    assert md.endswith("\n") and not md.endswith("\n\n")


def test_markdown_leaves_out_empty_sections():
    md = Context(title="T", summary="S", created_at=FIXED_TIME).to_markdown()
    assert "## Summary" in md
    for heading in ["Decisions", "Open questions", "Next steps", "Key facts", "Files", "Code"]:
        assert f"## {heading}" not in md
    assert "Saved 2026-11-09 14:30 UTC. This is the context" in md


def test_code_with_backticks_gets_longer_fence():
    snippet = CodeSnippet(content="```python\nprint(1)\n```", language="markdown")
    md = Context(title="T", summary="S", code=[snippet]).to_markdown()
    assert "````markdown\n```python\nprint(1)\n```\n````" in md

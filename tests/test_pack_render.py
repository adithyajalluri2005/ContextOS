import json
from datetime import datetime, timezone

import pytest

from contextos.pack import ContextPack, render
from contextos.pack.model import CodeSnippet, Decision, FileRef, Message, Source
from contextos.pack.render import CLAUDE_MD_END, CLAUDE_MD_START, render_claude_md, render_json, render_markdown


def at(day: int) -> datetime:
    return datetime(2026, 3, day, 12, 0, tzinfo=timezone.utc)


def full_pack(**overrides) -> ContextPack:
    data = dict(
        title="Speed up a slow SQL query",
        summary="The orders report was slow. An index fixed it.",
        decisions=[
            Decision(decision="Add an index on orders.customer_id", reason="The join scanned every row"),
            Decision(decision="Keep PostgreSQL 16"),
        ],
        open_questions=["Should old orders be archived?"],
        next_steps=["Run EXPLAIN again on the live database"],
        key_facts=["The orders table has 4 million rows"],
        code_snippets=[
            CodeSnippet(
                code="CREATE INDEX idx_orders_customer ON orders (customer_id);",
                language="sql",
                path="db/migrations/007.sql",
                description="The new index",
            )
        ],
        file_refs=[FileRef(path="reports/orders.py", description="Builds the slow report"), FileRef(path="README.md")],
        source=Source(
            tool="claude-ai",
            conversation_id="cl-1",
            title="Slow join",
            url="https://claude.ai/chat/cl-1",
            created_at=at(1),
            updated_at=at(5),
        ),
        created_at=at(7),
    )
    data.update(overrides)
    return ContextPack(**data)


def minimal_pack() -> ContextPack:
    return ContextPack(title="Short chat", summary="Nothing much.", source=Source(tool="chatgpt"), created_at=at(7))


# --- markdown ----------------------------------------------------------------


def test_markdown_has_every_section_in_order():
    md = render_markdown(full_pack())
    assert md.startswith("# Context: Speed up a slow SQL query\n")
    assert "continue the work" in md
    assert '_From Claude.ai, conversation "Slow join", 2026-03-01 to 2026-03-05, https://claude.ai/chat/cl-1._' in md
    headings = [ln for ln in md.splitlines() if ln.startswith("## ")]
    assert headings == [
        "## Summary",
        "## Decisions",
        "## Open questions",
        "## Next steps",
        "## Key facts",
        "## Files",
        "## Code",
    ]
    assert "- Add an index on orders.customer_id (reason: The join scanned every row)" in md
    assert "- Keep PostgreSQL 16\n" in md
    assert "- Should old orders be archived?" in md
    assert "- `reports/orders.py`: Builds the slow report" in md
    assert "- `README.md`\n" in md
    assert "`db/migrations/007.sql` - The new index\n```sql\nCREATE INDEX" in md
    assert md.endswith("\n") and not md.endswith("\n\n")


def test_markdown_leaves_out_empty_sections():
    md = render_markdown(minimal_pack())
    headings = [ln for ln in md.splitlines() if ln.startswith("## ")]
    assert headings == ["## Summary"]
    assert "_From ChatGPT._" in md


def test_unknown_tool_name_is_shown_as_is():
    md = render_markdown(full_pack(source=Source(tool="gemini")))
    assert "_From gemini._" in md


def test_same_day_shows_one_date():
    md = render_markdown(full_pack(source=Source(tool="chatgpt", created_at=at(2), updated_at=at(2))))
    assert "_From ChatGPT, 2026-03-02._" in md


def test_list_items_are_kept_on_one_line():
    md = render_markdown(full_pack(next_steps=["first line\nsecond line"]))
    assert "- first line second line" in md


def test_code_with_backticks_gets_a_longer_fence():
    code = 'print("""\n```\ninside\n```\n""")'
    md = render_markdown(full_pack(code_snippets=[CodeSnippet(code=code, language="python")]))
    assert "````python\n" + code + "\n````" in md


def test_transcript_only_when_present():
    assert "Full transcript" not in render_markdown(full_pack())
    pack = full_pack(raw_transcript=[Message(role="user", content="Why slow?"), Message(role="assistant", content="No index.")])
    md = render_markdown(pack)
    assert md.splitlines().count("## Full transcript") == 1
    assert "**user:**\n\nWhy slow?\n\n**assistant:**\n\nNo index." in md


# --- json --------------------------------------------------------------------


def test_json_round_trips():
    pack = full_pack()
    text = render_json(pack)
    assert text.endswith("}\n")
    assert ContextPack.from_json(text) == pack
    assert "raw_transcript" not in json.loads(text)


# --- claude-md ---------------------------------------------------------------


def test_claude_md_is_a_marked_section_with_lower_headings():
    text = render_claude_md(full_pack())
    lines = text.splitlines()
    assert lines[0] == CLAUDE_MD_START
    assert lines[-1] == CLAUDE_MD_END
    assert "## Context from an earlier conversation: Speed up a slow SQL query" in lines
    assert "Made by ContextOS on 2026-03-07." in text
    assert "### Decisions" in lines and "### Summary" in lines
    # No top-level heading, so it fits inside an existing CLAUDE.md.
    assert not any(ln.startswith("# ") for ln in lines)
    assert not any(ln.startswith("## Summary") for ln in lines)


# --- render() ----------------------------------------------------------------


@pytest.mark.parametrize("fmt", ["markdown", "json", "claude-md"])
def test_render_picks_the_format(fmt):
    assert render(full_pack(), fmt)


def test_render_rejects_unknown_format():
    with pytest.raises(ValueError, match="Unknown format 'html'"):
        render(full_pack(), "html")

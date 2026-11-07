"""Turn a Context Pack into text: Markdown to paste into a chat, JSON, or a CLAUDE.md section.

Renderers only format. They never change, drop or invent pack content, and empty
sections are left out so the output stays short.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timezone

from contextos.pack.model import CodeSnippet, ContextPack, Decision, FileRef, Message

FORMATS = ("markdown", "json", "claude-md")
CLAUDE_MD_START = "<!-- contextos:start -->"
CLAUDE_MD_END = "<!-- contextos:end -->"

TOOL_NAMES = {"chatgpt": "ChatGPT", "claude-ai": "Claude.ai", "claude-code": "Claude Code"}


def _tool(pack: ContextPack) -> str:
    return TOOL_NAMES.get(pack.source.tool, pack.source.tool)


def _date(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d") if value else None


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _fence(code: str) -> str:
    """A backtick fence longer than any backtick run inside the code, so the code cannot close it."""
    longest = max((len(run) for run in re.findall(r"`+", code)), default=0)
    return "`" * max(3, longest + 1)


def _decision(d: Decision) -> str:
    text = f"- {_one_line(d.decision)}"
    return f"{text} (reason: {_one_line(d.reason)})" if d.reason else text


def _file(f: FileRef) -> str:
    text = f"- `{f.path}`"
    return f"{text}: {_one_line(f.description)}" if f.description else text


def _snippet(s: CodeSnippet) -> str:
    label = " - ".join(_one_line(x) for x in (s.path and f"`{s.path}`", s.description) if x)
    fence = _fence(s.code)
    lines = [label] if label else []
    lines += [f"{fence}{s.language or ''}", s.code.rstrip("\n"), fence]
    return "\n".join(lines)


def _transcript(messages: list[Message]) -> str:
    return "\n\n".join(f"**{m.role}:**\n\n{m.content.strip()}" for m in messages)


def _source_line(pack: ContextPack) -> str:
    src = pack.source
    parts = [f"From {_tool(pack)}"]
    if src.title:
        parts.append(f'conversation "{_one_line(src.title)}"')
    started, updated = _date(src.created_at), _date(src.updated_at)
    if started and updated and started != updated:
        parts.append(f"{started} to {updated}")
    elif started or updated:
        parts.append(started or updated or "")
    if src.url:
        parts.append(src.url)
    return ", ".join(parts) + "."


def _sections(pack: ContextPack, level: int) -> list[str]:
    """The body sections, each with a heading of the given level. Empty sections are skipped."""
    h = "#" * level
    out = [f"{h} Summary\n\n{pack.summary.strip()}"]

    def add(title: str, items: list, fmt: Callable) -> None:
        if items:
            out.append(f"{h} {title}\n\n" + "\n".join(fmt(i) for i in items))

    add("Decisions", pack.decisions, _decision)
    add("Open questions", pack.open_questions, lambda q: f"- {_one_line(q)}")
    add("Next steps", pack.next_steps, lambda s: f"- {_one_line(s)}")
    add("Key facts", pack.key_facts, lambda f: f"- {_one_line(f)}")
    add("Files", pack.file_refs, _file)
    if pack.code_snippets:
        out.append(f"{h} Code\n\n" + "\n\n".join(_snippet(s) for s in pack.code_snippets))
    if pack.raw_transcript:
        out.append(f"{h} Full transcript\n\n{_transcript(pack.raw_transcript)}")
    return out


def render_markdown(pack: ContextPack) -> str:
    """Markdown to paste at the start of a new chat."""
    intro = (
        "This is a summary of an earlier conversation. Read it, then continue the work from "
        "where it stopped. Ask me if something important is missing."
    )
    parts = [f"# Context: {_one_line(pack.title)}", intro, f"_{_source_line(pack)}_", *_sections(pack, 2)]
    return "\n\n".join(parts) + "\n"


def render_json(pack: ContextPack) -> str:
    return pack.to_json() + "\n"


def render_claude_md(pack: ContextPack) -> str:
    """A section to add to CLAUDE.md or AGENTS.md. Markers let a later run find and replace it."""
    parts = [
        CLAUDE_MD_START,
        f"## Context from an earlier conversation: {_one_line(pack.title)}",
        f"_{_source_line(pack)} Made by ContextOS on {_date(pack.created_at)}._",
        *_sections(pack, 3),
        CLAUDE_MD_END,
    ]
    return "\n\n".join(parts) + "\n"


RENDERERS: dict[str, Callable[[ContextPack], str]] = {
    "markdown": render_markdown,
    "json": render_json,
    "claude-md": render_claude_md,
}


def render(pack: ContextPack, fmt: str = "markdown") -> str:
    try:
        return RENDERERS[fmt](pack)
    except KeyError:
        raise ValueError(f"Unknown format '{fmt}'. Choose one of: {', '.join(FORMATS)}.") from None


__all__ = ["CLAUDE_MD_END", "CLAUDE_MD_START", "FORMATS", "render", "render_claude_md", "render_json", "render_markdown"]

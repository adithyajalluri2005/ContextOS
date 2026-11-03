"""Importer for Claude Code session transcripts.

Claude Code saves every session on your computer as one JSONL file (one JSON object
per line) under ~/.claude/projects/<project-folder>/<session-id>.jsonl. Set
CLAUDE_CONFIG_DIR to change where ~/.claude is.

Each line has a `type`. We use:
- "user" and "assistant": the conversation. `parentUuid` links each line to the one
  before it. Rewinding a session makes a branch; we keep the branch that ends at the
  last line of the file. After compaction a new chain starts with parentUuid null, and
  a "system" line points back with `logicalParentUuid`, so we follow that too.
  Other lines with a uuid ("attachment", "system") are links in the chain too, but are
  not shown.
- "custom-title" and "ai-title": the session's title.
All other line types (cost, mode, API requests, file history, ...) are ignored.

What we keep: your prompts, Claude's text answers, and one short line per tool call,
for example `[ran: pytest -q]` or `[edited file: src/app.py]`. What we drop: tool
results (they can be huge), hidden thinking, subagent (sidechain) messages, status
messages, and API errors. Subagent files in subfolders are not read.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from contextos.importers.base import ImportFailed, ParsedExport, parse_iso
from contextos.pack import Message
from contextos.store import ConversationIn

__all__ = ["SOURCE_TOOL", "default_projects_dir", "find_session_files", "parse_session", "read_sessions"]

SOURCE_TOOL = "claude-code"
MAX_TOOL_ARG_CHARS = 200
MAX_TITLE_CHARS = 80

# Text that Claude Code adds to the user side but that the user did not write.
_HIDDEN_PREFIXES = (
    "<task-notification>",
    "<local-command-caveat>",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<system-reminder>",
    "<bash-stdout>",
    "<bash-stderr>",
)
_COMMAND_NAME = re.compile(r"<command-name>\s*(.*?)\s*</command-name>", re.S)
_COMMAND_ARGS = re.compile(r"<command-args>\s*(.*?)\s*</command-args>", re.S)

# Which input field best describes each tool call, and how to label it.
_TOOL_LABELS: dict[str, tuple[str, str]] = {
    "Bash": ("ran", "command"),
    "PowerShell": ("ran", "command"),
    "Read": ("read file", "file_path"),
    "Write": ("wrote file", "file_path"),
    "Edit": ("edited file", "file_path"),
    "MultiEdit": ("edited file", "file_path"),
    "NotebookEdit": ("edited notebook", "notebook_path"),
    "Glob": ("searched files", "pattern"),
    "Grep": ("searched for", "pattern"),
    "WebFetch": ("fetched", "url"),
    "WebSearch": ("searched the web for", "query"),
    "Agent": ("asked a helper agent", "description"),
    "Task": ("asked a helper agent", "description"),
}


# --- finding files ---------------------------------------------------------


def default_projects_dir() -> Path:
    config = os.environ.get("CLAUDE_CONFIG_DIR")
    base = Path(config).expanduser() if config else Path.home() / ".claude"
    return base / "projects"


def find_session_files(path: Path) -> list[Path]:
    """Session files under `path`: the projects folder, one project folder, or one file."""
    if not path.exists():
        raise ImportFailed(f"Not found: {path}")
    if path.is_file():
        if path.suffix.lower() != ".jsonl":
            raise ImportFailed(f"{path.name} is not a .jsonl session file.")
        return [path]
    direct = sorted(path.glob("*.jsonl"))
    if direct:  # one project folder
        return direct
    files = sorted(path.glob("*/*.jsonl"))  # the projects folder; deeper files are subagents
    if not files:
        raise ImportFailed(f"No Claude Code sessions (.jsonl files) found in {path}")
    return files


# --- reading one session ---------------------------------------------------


def _read_lines(path: Path) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue  # a half-written last line, for example
            if isinstance(obj, dict):
                lines.append(obj)
    return lines


def _main_chain(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Conversation lines on the branch ending at the last message of the file."""
    # Any line with a uuid can be a link in the chain ("attachment" and "system" lines too).
    linked = [ln for ln in lines if isinstance(ln.get("uuid"), str) and not ln.get("isSidechain")]
    if not linked:
        return []
    by_uuid = {ln["uuid"]: ln for ln in linked}
    last = next((ln for ln in reversed(linked) if ln.get("type") in ("user", "assistant")), None)
    if last is None:
        return []

    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    node: dict[str, Any] | None = last
    while node is not None and node["uuid"] not in seen:  # `seen` guards against broken loops
        seen.add(node["uuid"])
        chain.append(node)
        parent = node.get("parentUuid") or node.get("logicalParentUuid")
        node = by_uuid.get(parent) if parent else None
    chain.reverse()
    return chain


def _short(value: Any, limit: int = MAX_TOOL_ARG_CHARS) -> str:
    text = " ".join(str(value).split())  # one line
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _tool_line(block: dict[str, Any]) -> str:
    name = str(block.get("name") or "a tool")
    args = block.get("input") if isinstance(block.get("input"), dict) else {}
    label, field = _TOOL_LABELS.get(name, ("used tool", ""))
    if field and args.get(field):
        return f"[{label}: {_short(args[field])}]"
    return f"[used tool: {name}]"


def _user_text(text: str) -> str | None:
    stripped = text.strip()
    if not stripped:
        return None
    name = _COMMAND_NAME.search(stripped)
    if name:  # the user typed a slash command
        args = _COMMAND_ARGS.search(stripped)
        command = name.group(1) if name.group(1).startswith("/") else f"/{name.group(1)}"
        extra = f" {_short(args.group(1))}" if args and args.group(1) else ""
        return f"[command: {command}{extra}]"
    if stripped.startswith(_HIDDEN_PREFIXES):
        return None
    return stripped


COMPACTED_NOTE = "[Claude Code compacted the conversation here]"


def _to_message(line: dict[str, Any]) -> Message | None:
    kind = line.get("type")
    if kind == "system" and line.get("subtype") == "compact_boundary":
        return Message(role="system", content=COMPACTED_NOTE, created_at=parse_iso(line.get("timestamp")))
    if kind not in ("user", "assistant"):
        return None
    if line.get("isMeta") or line.get("isCompactSummary") or line.get("isApiErrorMessage"):
        return None
    msg = line.get("message")
    if not isinstance(msg, dict):
        return None
    content = msg.get("content")
    blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
    if not isinstance(blocks, list):
        return None

    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text" and isinstance(block.get("text"), str):
            text = _user_text(block["text"]) if kind == "user" else (block["text"].strip() or None)
            if text:
                parts.append(text)
        elif btype == "tool_use" and kind == "assistant":
            parts.append(_tool_line(block))
        elif btype == "image":
            parts.append("[image]")
        # thinking, tool_result and anything new are left out.
    if not parts:
        return None
    return Message(role=kind, content="\n\n".join(parts), created_at=parse_iso(line.get("timestamp")))


def _merge_runs(messages: list[Message]) -> list[Message]:
    """Claude Code writes one line per answer block; join back-to-back assistant lines."""
    merged: list[Message] = []
    for m in messages:
        if merged and m.role == "assistant" and merged[-1].role == "assistant":
            prev = merged[-1]
            merged[-1] = Message(role="assistant", content=f"{prev.content}\n\n{m.content}",
                                 created_at=prev.created_at)
        else:
            merged.append(m)
    return merged


def _title(lines: list[dict[str, Any]], messages: list[Message]) -> str | None:
    for kind, key in (("custom-title", "customTitle"), ("ai-title", "aiTitle"), ("summary", "summary")):
        values = [ln.get(key) for ln in lines if ln.get("type") == kind and isinstance(ln.get(key), str)]
        values = [v.strip() for v in values if v.strip()]
        if values:
            return values[-1]  # the newest title wins
    first = next((m.content for m in messages if m.role == "user" and not m.content.startswith("[")), None)
    return _short(first, MAX_TITLE_CHARS) if first else None


def parse_session(path: Path) -> ConversationIn:
    """Turn one session file into a ConversationIn. Raises ValueError if unusable."""
    lines = _read_lines(path)
    chain = _main_chain(lines)
    messages = _merge_runs([m for m in (_to_message(ln) for ln in chain) if m])
    if not messages:
        raise ValueError("no visible messages")

    first = next((ln for ln in chain if ln.get("cwd")), {})
    session_id = next((ln.get("sessionId") for ln in chain if ln.get("sessionId")), None) or path.stem
    if first.get("cwd"):
        branch = f" (git branch: {first['gitBranch']})" if first.get("gitBranch") else ""
        messages.insert(0, Message(role="system", content=f"Working folder: {first['cwd']}{branch}"))

    times = [t for t in (parse_iso(ln.get("timestamp")) for ln in chain) if t]
    return ConversationIn(
        source_tool=SOURCE_TOOL,
        source_id=str(session_id),
        title=_title(lines, messages),
        url=None,
        created_at=min(times) if times else None,
        updated_at=max(times) if times else None,
        messages=messages,
    )


def read_sessions(path: Path | str | None = None) -> ParsedExport:
    """Read every session under `path` (default: ~/.claude/projects)."""
    root = Path(path) if path is not None else default_projects_dir()
    result = ParsedExport()
    for file in find_session_files(root):
        label = f"{file.parent.name}/{file.name}"
        try:
            result.conversations.append(parse_session(file))
        except ValueError as exc:
            result.skipped.append(f"{label}: {exc}")
        except OSError as exc:
            result.skipped.append(f"{label}: could not read file ({exc.strerror or exc})")
    return result

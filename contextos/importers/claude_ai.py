"""Importer for the official Claude.ai data export.

How to get the export: Claude → Settings → Privacy → Export data. You get an email with
a ZIP file. Inside is `conversations.json`: a list of conversations, each with a
`chat_messages` list. (The ZIP also has users.json and projects.json; we ignore them.)

Messages have `sender` "human" or "assistant". Newer exports also give each message a
`parent_message_uuid`, because editing a message or retrying an answer makes a branch.
When those links exist, we keep the branch that ends at the newest message.

Each message has a plain `text` field and, in newer exports, a `content` list of blocks
(text, thinking, tool_use, tool_result). We read the blocks when they are there.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from contextos.importers.base import (
    ParsedExport,
    cut,
    load_json_lists,
    parse_iso,
    run_parser,
)
from contextos.pack import Message
from contextos.store import ConversationIn

__all__ = ["SOURCE_TOOL", "parse_conversation", "read_export"]

SOURCE_TOOL = "claude-ai"
CHAT_URL = "https://claude.ai/chat/{id}"
ROOT_PARENT = "00000000-0000-4000-8000-000000000000"

_CONV_FILE = re.compile(r"(?:^|/)conversations\.json$")
_ROLES = {"human": "user", "user": "user", "assistant": "assistant"}


# --- message tree ----------------------------------------------------------


def _sort_key(msg: dict[str, Any]) -> tuple:
    created = parse_iso(msg.get("created_at"))
    return (created.timestamp() if created else 0.0, msg.get("index") or 0)


def _branch(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Messages on the branch that ends at the newest message.

    Older exports have no parent links; their list is already the conversation in order.
    """
    by_id = {m["uuid"]: m for m in messages if isinstance(m.get("uuid"), str)}
    has_links = any(m.get("parent_message_uuid") for m in messages)
    if not has_links or not by_id:
        return messages

    newest = max(by_id.values(), key=_sort_key)
    path: list[dict[str, Any]] = []
    seen: set[str] = set()
    node: dict[str, Any] | None = newest
    while node is not None and node["uuid"] not in seen:  # `seen` guards against broken loops
        seen.add(node["uuid"])
        path.append(node)
        parent = node.get("parent_message_uuid")
        node = by_id.get(parent) if parent and parent != ROOT_PARENT else None
    path.reverse()
    return path


# --- message content -------------------------------------------------------


def _block_text(block: Any) -> str | None:
    if not isinstance(block, dict):
        return None
    btype = block.get("type")
    if btype == "text":
        text = block.get("text")
        return text if isinstance(text, str) and text.strip() else None
    if btype == "tool_use":
        name = block.get("name") or "a tool"
        return f"[used tool: {name}]"
    # thinking (hidden reasoning), tool_result (raw tool output), images, and anything
    # new are left out to keep the conversation readable and the pack small.
    return None


def _attachments_text(msg: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    for att in msg.get("attachments") or []:
        if not isinstance(att, dict):
            continue
        name = att.get("file_name") or "attachment"
        content = att.get("extracted_content")
        if isinstance(content, str) and content.strip():
            parts.append(f"[attached file: {name}]\n{cut(content.strip())}")
        else:
            parts.append(f"[attached file: {name}]")
    for f in msg.get("files") or []:
        if isinstance(f, dict):
            parts.append(f"[file: {f.get('file_name') or 'file'}]")
    return parts


def _message_text(msg: dict[str, Any]) -> str | None:
    blocks = msg.get("content")
    if isinstance(blocks, list) and blocks:
        parts = [t for t in (_block_text(b) for b in blocks) if t]
    else:
        text = msg.get("text")
        parts = [text] if isinstance(text, str) and text.strip() else []
    parts += _attachments_text(msg)
    return "\n\n".join(parts) or None


def _to_message(msg: Any) -> Message | None:
    if not isinstance(msg, dict):
        return None
    role = _ROLES.get(str(msg.get("sender", "")).lower())
    if role is None:
        return None
    text = _message_text(msg)
    if text is None:
        return None
    return Message(role=role, content=text, created_at=parse_iso(msg.get("created_at")))


# --- one conversation ------------------------------------------------------


def parse_conversation(raw: dict[str, Any]) -> ConversationIn:
    """Turn one raw Claude.ai conversation into a ConversationIn. Raises ValueError if unusable."""
    if not isinstance(raw, dict):
        raise ValueError("entry is not an object")
    conv_id = raw.get("uuid")
    if not conv_id:
        raise ValueError("missing conversation id")
    chat_messages = raw.get("chat_messages")
    if not isinstance(chat_messages, list):
        raise ValueError("missing chat_messages list")

    messages = [m for m in (_to_message(x) for x in _branch(chat_messages)) if m]
    if not messages:
        raise ValueError("no visible messages")

    return ConversationIn(
        source_tool=SOURCE_TOOL,
        source_id=str(conv_id),
        title=raw.get("name") or None,
        url=CHAT_URL.format(id=conv_id),
        created_at=parse_iso(raw.get("created_at")),
        updated_at=parse_iso(raw.get("updated_at")),
        messages=messages,
    )


def read_export(path: Path | str) -> ParsedExport:
    """Read a Claude.ai export. Bad conversations are skipped with a reason, not fatal."""
    raw_items = load_json_lists(Path(path), _CONV_FILE, "Claude")
    return run_parser(raw_items, parse_conversation, title_key="name")

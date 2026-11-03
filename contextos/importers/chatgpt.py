"""Importer for the official ChatGPT data export.

How to get the export: ChatGPT → Settings → Data controls → Export data. You get an
email with a ZIP file. Inside is `conversations.json`: a list of conversations.

Each conversation stores its messages as a tree (`mapping`), because editing a message
or asking for a new answer creates a new branch. `current_node` is the message the user
last saw. We walk from it up to the root, so we keep exactly the branch the user ended on.

The ZIP is read in memory. Nothing is extracted to disk.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from contextos.importers.base import (
    MAX_TOOL_CHARS,
    ParsedExport,
    cut,
    load_json_lists,
    run_parser,
)
from contextos.importers.base import parse_epoch as _timestamp
from contextos.pack import Message
from contextos.store import ConversationIn

__all__ = ["MAX_TOOL_CHARS", "SOURCE_TOOL", "parse_conversation", "read_export"]

SOURCE_TOOL = "chatgpt"
CHAT_URL = "https://chatgpt.com/c/{id}"

# conversations.json, or split files like conversations-000.json. Not shared_conversations.json.
_CONV_FILE = re.compile(r"(?:^|/)conversations(?:-\d+)?\.json$")
_ROLES = {"user", "assistant", "system", "tool"}


def _branch(mapping: dict[str, Any], current_node: str | None) -> list[dict[str, Any]]:
    """Nodes from the root down to current_node (or to the newest leaf if it is missing)."""
    if current_node not in mapping:
        leaves = [n for n in mapping.values() if isinstance(n, dict) and not n.get("children")]
        if not leaves:
            return []
        current_node = max(
            leaves, key=lambda n: ((n.get("message") or {}).get("create_time") or 0)
        ).get("id")

    path: list[dict[str, Any]] = []
    seen: set[str] = set()
    node_id = current_node
    while node_id in mapping and node_id not in seen:  # `seen` guards against broken loops
        seen.add(node_id)
        node = mapping[node_id]
        path.append(node)
        node_id = node.get("parent")
    path.reverse()
    return path


def _part_text(part: Any) -> str | None:
    if isinstance(part, str):
        return part if part.strip() else None
    if not isinstance(part, dict):
        return None
    ptype = str(part.get("content_type", ""))
    if ptype == "audio_transcription" and isinstance(part.get("text"), str):
        return part["text"]
    if "image" in ptype:
        return "[image]"
    if "audio" in ptype or "video" in ptype:
        return None
    text = part.get("text")
    return text if isinstance(text, str) and text.strip() else None


def _message_text(content: dict[str, Any]) -> str | None:
    """Readable text for one message, or None if it has nothing a person would read."""
    ctype = content.get("content_type")
    if ctype in ("text", "multimodal_text"):
        parts = [t for t in (_part_text(p) for p in content.get("parts") or []) if t]
        return "\n\n".join(parts) or None
    if ctype == "code":
        text = content.get("text") or ""
        lang = content.get("language") or ""
        lang = "" if lang == "unknown" else lang
        return f"```{lang}\n{text}\n```" if text.strip() else None
    if ctype in ("execution_output", "tether_quote", "system_error"):
        text = content.get("text") or ""
        return text if text.strip() else None
    if ctype == "tether_browsing_display":
        text = content.get("result") or ""
        return text if text.strip() else None
    # thoughts, reasoning_recap, user_editable_context, model_editable_context, and
    # anything new: internal or settings data, not part of the conversation.
    return None


def _to_message(node: dict[str, Any]) -> Message | None:
    msg = node.get("message")
    if not isinstance(msg, dict):
        return None
    metadata = msg.get("metadata") or {}
    if metadata.get("is_visually_hidden_from_conversation"):
        return None
    role = (msg.get("author") or {}).get("role")
    if role not in _ROLES:
        return None
    text = _message_text(msg.get("content") or {})
    if text is None:
        return None
    if role == "tool":
        text = cut(text)
    return Message(role=role, content=text, created_at=_timestamp(msg.get("create_time")))


def parse_conversation(raw: dict[str, Any]) -> ConversationIn:
    """Turn one raw ChatGPT conversation into a ConversationIn. Raises ValueError if unusable."""
    if not isinstance(raw, dict):
        raise ValueError("entry is not an object")
    conv_id = raw.get("conversation_id") or raw.get("id")
    if not conv_id:
        raise ValueError("missing conversation id")
    mapping = raw.get("mapping")
    if not isinstance(mapping, dict):
        raise ValueError("missing message tree")

    messages = [m for m in (_to_message(n) for n in _branch(mapping, raw.get("current_node"))) if m]
    if not messages:
        raise ValueError("no visible messages")

    return ConversationIn(
        source_tool=SOURCE_TOOL,
        source_id=str(conv_id),
        title=raw.get("title") or None,
        url=CHAT_URL.format(id=conv_id),
        created_at=_timestamp(raw.get("create_time")),
        updated_at=_timestamp(raw.get("update_time")),
        messages=messages,
    )


def read_export(path: Path | str) -> ParsedExport:
    """Read a ChatGPT export. Bad conversations are skipped with a reason, not fatal."""
    raw_items = load_json_lists(Path(path), _CONV_FILE, "ChatGPT")
    return run_parser(raw_items, parse_conversation, title_key="title")

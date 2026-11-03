"""Importer for the official ChatGPT data export.

How to get the export: ChatGPT → Settings → Data controls → Export data. You get an
email with a ZIP file. Inside is `conversations.json`: a list of conversations.

Each conversation stores its messages as a tree (`mapping`), because editing a message
or asking for a new answer creates a new branch. `current_node` is the message the user
last saw. We walk from it up to the root, so we keep exactly the branch the user ended on.

The ZIP is read in memory. Nothing is extracted to disk.
"""

from __future__ import annotations

import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from contextos.importers.base import ImportFailed, ParsedExport
from contextos.pack import Message
from contextos.store import ConversationIn

SOURCE_TOOL = "chatgpt"
CHAT_URL = "https://chatgpt.com/c/{id}"
# Tool output (code results, web pages) can be huge. Keep the start, which is usually enough.
MAX_TOOL_CHARS = 4000

# conversations.json, or split files like conversations-000.json. Not shared_conversations.json.
_CONV_FILE = re.compile(r"(?:^|/)conversations(?:-\d+)?\.json$")
_ROLES = {"user", "assistant", "system", "tool"}


# --- reading the files -----------------------------------------------------


def _decode(raw: bytes, name: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ImportFailed(f"{name} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ImportFailed(f"{name} should contain a list of conversations.")
    return data


def load_raw_conversations(path: Path) -> list[dict[str, Any]]:
    """Read every conversation from a ZIP, a folder, or a conversations.json file."""
    if not path.exists():
        raise ImportFailed(f"File not found: {path}")

    if path.is_dir():
        files = sorted(p for p in path.rglob("*.json") if _CONV_FILE.search(p.as_posix()))
        if not files:
            raise ImportFailed(f"No conversations.json found in folder {path}")
        return [c for f in files for c in _decode(f.read_bytes(), f.name)]

    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            names = sorted(
                n for n in zf.namelist() if _CONV_FILE.search(n) and not n.startswith("__MACOSX/")
            )
            if not names:
                raise ImportFailed(
                    f"{path.name} has no conversations.json. Is this a ChatGPT data export?"
                )
            return [c for n in names for c in _decode(zf.read(n), n)]

    if path.suffix.lower() == ".json":
        return _decode(path.read_bytes(), path.name)

    raise ImportFailed(f"{path.name} is not a ZIP file or a .json file.")


# --- one conversation ------------------------------------------------------


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


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


def _cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[... {len(text) - limit} more characters cut]"


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
        text = _cut(text, MAX_TOOL_CHARS)
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
    result = ParsedExport()
    for index, raw in enumerate(load_raw_conversations(Path(path))):
        label = (raw.get("title") if isinstance(raw, dict) else None) or f"conversation #{index + 1}"
        try:
            result.conversations.append(parse_conversation(raw))
        except (ValueError, ValidationError) as exc:
            reason = exc.errors()[0]["msg"] if isinstance(exc, ValidationError) else str(exc)
            result.skipped.append(f"{label}: {reason}")
    return result

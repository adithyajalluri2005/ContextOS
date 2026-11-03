"""Shared pieces for importers.

An importer reads one tool's export and returns a `ParsedExport`. It never writes to
the store itself; `save_all()` does that, so every importer reports results the same way.
"""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from contextos.store import ConversationIn, Store

# Tool output and pasted files can be huge. Keep the start, which is usually enough.
MAX_TOOL_CHARS = 4000


class ImportFailed(Exception):
    """The export as a whole could not be read. The message is shown to the user."""


@dataclass
class ParsedExport:
    conversations: list[ConversationIn] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # one plain-English reason per skipped chat


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.created + self.updated + self.unchanged


def _decode_list(raw: bytes, name: str) -> list[Any]:
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ImportFailed(f"{name} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ImportFailed(f"{name} should contain a list of conversations.")
    return data


def load_json_lists(path: Path, file_pattern: re.Pattern[str], product: str) -> list[Any]:
    """Read and join every JSON list whose path matches `file_pattern`.

    `path` can be the export ZIP (read in memory, nothing extracted), the unzipped
    folder, or one .json file. `product` is used in error messages, e.g. "ChatGPT".
    """
    if not path.exists():
        raise ImportFailed(f"File not found: {path}")

    if path.is_dir():
        files = sorted(p for p in path.rglob("*.json") if file_pattern.search(p.as_posix()))
        if not files:
            raise ImportFailed(f"No conversations.json found in folder {path}")
        return [c for f in files for c in _decode_list(f.read_bytes(), f.name)]

    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            names = sorted(
                n for n in zf.namelist() if file_pattern.search(n) and not n.startswith("__MACOSX/")
            )
            if not names:
                raise ImportFailed(
                    f"{path.name} has no conversations.json. Is this a {product} data export?"
                )
            return [c for n in names for c in _decode_list(zf.read(n), n)]

    if path.suffix.lower() == ".json":
        return _decode_list(path.read_bytes(), path.name)

    raise ImportFailed(f"{path.name} is not a ZIP file or a .json file.")


def cut(text: str, limit: int = MAX_TOOL_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[... {len(text) - limit} more characters cut]"


def parse_epoch(value: Any) -> datetime | None:
    """Seconds since 1970 -> UTC datetime. Bad or missing values -> None."""
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def parse_iso(value: Any) -> datetime | None:
    """ISO 8601 text -> datetime. A date without a time zone is taken as UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def run_parser(raw_items: list[Any], parse, title_key: str) -> ParsedExport:
    """Call `parse` on each raw conversation. Failures are skipped with a reason."""
    result = ParsedExport()
    for index, raw in enumerate(raw_items):
        label = (raw.get(title_key) if isinstance(raw, dict) else None) or f"conversation #{index + 1}"
        try:
            result.conversations.append(parse(raw))
        except ValueError as exc:  # pydantic's ValidationError is a ValueError too
            reason = exc.errors()[0]["msg"] if isinstance(exc, ValidationError) else str(exc)
            result.skipped.append(f"{label}: {reason}")
    return result


def save_all(parsed: ParsedExport, store: Store) -> ImportResult:
    result = ImportResult(skipped=list(parsed.skipped))
    for conv in parsed.conversations:
        _, status = store.save(conv)
        setattr(result, status, getattr(result, status) + 1)
    return result

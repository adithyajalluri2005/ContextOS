"""Local storage for imported conversations, using SQLite.

Importers turn each tool's export into a `ConversationIn` and call `Store.save()`.
A conversation is identified by (source_tool, source_id), so importing the same
export twice updates the existing row instead of adding a copy.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from contextos.pack import Message

HOME_ENV = "CONTEXTOS_HOME"
DB_FILENAME = "contextos.db"
SCHEMA_VERSION = 1

SaveStatus = Literal["created", "updated", "unchanged"]

_SCHEMA = """
CREATE TABLE conversations (
    id            INTEGER PRIMARY KEY,
    source_tool   TEXT NOT NULL,
    source_id     TEXT NOT NULL,
    title         TEXT,
    url           TEXT,
    created_at    TEXT,
    updated_at    TEXT,
    imported_at   TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    UNIQUE (source_tool, source_id)
);

CREATE TABLE messages (
    id               INTEGER PRIMARY KEY,
    conversation_id  INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    position         INTEGER NOT NULL,
    role             TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    content          TEXT NOT NULL,
    created_at       TEXT,
    UNIQUE (conversation_id, position)
);

CREATE INDEX idx_conversations_source ON conversations(source_tool);
"""


def contextos_home() -> Path:
    """Folder for ContextOS data: $CONTEXTOS_HOME, or ~/.contextos."""
    override = os.environ.get(HOME_ENV)
    return Path(override).expanduser() if override else Path.home() / ".contextos"


def default_db_path() -> Path:
    return contextos_home() / DB_FILENAME


class ConversationIn(BaseModel):
    """A conversation as an importer hands it to the store."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_tool: str = Field(min_length=1, description='e.g. "chatgpt", "claude-ai", "claude-code"')
    source_id: str = Field(min_length=1, description="ID of the conversation in the original tool.")
    title: str | None = None
    url: str | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None
    messages: list[Message] = Field(default_factory=list)

    def content_hash(self) -> str:
        """Fingerprint of everything we store, used to tell if a re-import changed anything."""
        data = self.model_dump(mode="json")
        raw = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


class ConversationSummary(BaseModel):
    """One row for `contextos list`."""

    id: int
    source_tool: str
    source_id: str
    title: str | None
    url: str | None
    created_at: datetime | None
    updated_at: datetime | None
    imported_at: datetime
    message_count: int


class Conversation(ConversationSummary):
    """A stored conversation with its messages."""

    messages: list[Message]


def _to_db(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _from_db(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class Store:
    """SQLite store. Use as a context manager, or call close() when done."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    # --- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._conn:  # commits on success, rolls back on error
            yield self._conn

    def _migrate(self) -> None:
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"{self.path} was made by a newer ContextOS (schema {version}); please upgrade."
            )
        if version == 0:
            with self._transaction() as conn:
                conn.executescript(_SCHEMA)
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    # --- writes ------------------------------------------------------------

    def save(self, conv: ConversationIn) -> tuple[int, SaveStatus]:
        """Insert a conversation, or update it if (source_tool, source_id) is already stored."""
        digest = conv.content_hash()
        now = _to_db(datetime.now(timezone.utc))
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT id, content_hash FROM conversations WHERE source_tool = ? AND source_id = ?",
                (conv.source_tool, conv.source_id),
            ).fetchone()
            if row is not None and row["content_hash"] == digest:
                return row["id"], "unchanged"

            fields = (conv.title, conv.url, _to_db(conv.created_at), _to_db(conv.updated_at), now, digest)
            if row is None:
                conv_id = conn.execute(
                    "INSERT INTO conversations (source_tool, source_id, title, url, created_at, updated_at,"
                    " imported_at, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (conv.source_tool, conv.source_id, *fields),
                ).lastrowid
                status: SaveStatus = "created"
            else:
                conv_id = row["id"]
                conn.execute(
                    "UPDATE conversations SET title = ?, url = ?, created_at = ?, updated_at = ?,"
                    " imported_at = ?, content_hash = ? WHERE id = ?",
                    (*fields, conv_id),
                )
                conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
                status = "updated"

            conn.executemany(
                "INSERT INTO messages (conversation_id, position, role, content, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                [
                    (conv_id, pos, m.role, m.content, _to_db(m.created_at))
                    for pos, m in enumerate(conv.messages)
                ],
            )
            return conv_id, status

    # --- reads -------------------------------------------------------------

    _SUMMARY_SELECT = """
        SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count
        FROM conversations c
    """

    @staticmethod
    def _summary(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "source_tool": row["source_tool"],
            "source_id": row["source_id"],
            "title": row["title"],
            "url": row["url"],
            "created_at": _from_db(row["created_at"]),
            "updated_at": _from_db(row["updated_at"]),
            "imported_at": _from_db(row["imported_at"]),
            "message_count": row["message_count"],
        }

    def list_conversations(self, source_tool: str | None = None) -> list[ConversationSummary]:
        """Newest first (by last change, then start date, then import order)."""
        sql = self._SUMMARY_SELECT
        params: tuple = ()
        if source_tool:
            sql += " WHERE c.source_tool = ?"
            params = (source_tool,)
        sql += " ORDER BY COALESCE(c.updated_at, c.created_at, c.imported_at) DESC, c.id DESC"
        rows = self._conn.execute(sql, params).fetchall()
        return [ConversationSummary(**self._summary(r)) for r in rows]

    def get(self, conversation_id: int) -> Conversation | None:
        row = self._conn.execute(self._SUMMARY_SELECT + " WHERE c.id = ?", (conversation_id,)).fetchone()
        if row is None:
            return None
        msgs = self._conn.execute(
            "SELECT role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY position",
            (conversation_id,),
        ).fetchall()
        messages = [
            Message(role=m["role"], content=m["content"], created_at=_from_db(m["created_at"])) for m in msgs
        ]
        return Conversation(**self._summary(row), messages=messages)

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]

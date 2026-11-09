"""Local storage for saved contexts: one SQLite file on your computer.

The file is `contextos.db` in the folder named by the CONTEXTOS_HOME environment
variable, or in `~/.contextos` when it is not set. Nothing here talks to the network.
"""

import os
import sqlite3
from contextlib import closing
from pathlib import Path

from contextos.context import Context

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS contexts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    source_tool TEXT,
    created_at  TEXT NOT NULL,   -- ISO time in UTC, so text order is time order
    search_text TEXT NOT NULL,   -- lower-case text of all fields, used by search()
    body        TEXT NOT NULL    -- the full context as JSON
);
CREATE INDEX IF NOT EXISTS contexts_created ON contexts (created_at);
"""


def default_db_path() -> Path:
    """Where the database lives: $CONTEXTOS_HOME/contextos.db, else ~/.contextos/contextos.db."""
    home = os.environ.get("CONTEXTOS_HOME")
    folder = Path(home) if home else Path.home() / ".contextos"
    return folder / "contextos.db"


class Store:
    """Save, find, load and delete contexts."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.executescript(_SCHEMA)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    # --- writing ---------------------------------------------------------------

    def save(self, context: Context) -> Context:
        """Save a new context and return it with its new `id`.

        An `id` already on the context is ignored: saving always adds a new entry.
        """
        ctx = context.model_copy(update={"id": None})
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "INSERT INTO contexts (title, source_tool, created_at, search_text, body)"
                " VALUES (?, ?, ?, ?, '')",
                (ctx.title, ctx.source_tool, ctx.created_at.isoformat(), _search_text(ctx)),
            )
            saved = ctx.model_copy(update={"id": str(cursor.lastrowid)})
            conn.execute(
                "UPDATE contexts SET body = ? WHERE id = ?",
                (saved.model_dump_json(), cursor.lastrowid),
            )
        return saved

    def delete(self, context_id: str) -> bool:
        """Delete one context. Returns False if there was no context with that id."""
        row_id = _row_id(context_id)
        if row_id is None:
            return False
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute("DELETE FROM contexts WHERE id = ?", (row_id,))
        return cursor.rowcount > 0

    # --- reading ---------------------------------------------------------------

    def get(self, context_id: str) -> Context | None:
        """Load one context by id, or None if there is none."""
        row_id = _row_id(context_id)
        if row_id is None:
            return None
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT body FROM contexts WHERE id = ?", (row_id,)).fetchone()
        return Context.model_validate_json(row[0]) if row else None

    def recent(self, *, limit: int = 20, source_tool: str | None = None) -> list[Context]:
        """Saved contexts, newest first. `source_tool` keeps only one tool's contexts."""
        sql = "SELECT body FROM contexts"
        params: list[object] = []
        if source_tool:
            sql += " WHERE source_tool = ?"
            params.append(source_tool)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(max(limit, 0))
        return self._fetch(sql, params)

    def search(self, query: str, *, limit: int = 20) -> list[Context]:
        """Contexts that contain every word of `query`, newest first. Case does not matter.

        An empty query finds nothing.
        """
        words = query.lower().split()
        if not words:
            return []
        sql = "SELECT body FROM contexts WHERE "
        sql += " AND ".join("search_text LIKE ? ESCAPE '!'" for _ in words)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params: list[object] = [f"%{_escape_like(w)}%" for w in words]
        params.append(max(limit, 0))
        return self._fetch(sql, params)

    def _fetch(self, sql: str, params: list[object]) -> list[Context]:
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [Context.model_validate_json(row[0]) for row in rows]


def _search_text(ctx: Context) -> str:
    """All the words a search can match, in lower case."""
    parts = [ctx.title, ctx.summary, *ctx.decisions, *ctx.open_questions, *ctx.next_steps]
    parts += ctx.key_facts
    parts += [f"{ref.path} {ref.note}" for ref in ctx.files]
    parts += [f"{c.note} {c.content}" for c in ctx.code]
    parts += [ctx.source_tool or "", ctx.project_dir or ""]
    return "\n".join(parts).lower()


def _row_id(context_id: str) -> int | None:
    """Turn an id like "12" into 12. Anything else is not a valid id."""
    text = str(context_id).strip()
    return int(text) if text.isdigit() else None


def _escape_like(word: str) -> str:
    """Make %, _ and ! plain characters inside a LIKE pattern."""
    return word.replace("!", "!!").replace("%", "!%").replace("_", "!_")

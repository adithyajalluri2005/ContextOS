"""Shared pieces for importers.

An importer reads one tool's export and returns a `ParsedExport`. It never writes to
the store itself; `save_all()` does that, so every importer reports results the same way.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from contextos.store import ConversationIn, Store


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


def save_all(parsed: ParsedExport, store: Store) -> ImportResult:
    result = ImportResult(skipped=list(parsed.skipped))
    for conv in parsed.conversations:
        _, status = store.save(conv)
        setattr(result, status, getattr(result, status) + 1)
    return result

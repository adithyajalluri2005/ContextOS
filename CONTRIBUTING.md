# Contributing to ContextOS

Thank you for helping. This guide covers the setup, the rules for tests, and the most
common kind of change: adding an importer for a new AI tool.

## Setup

Needs Python 3.12 or newer.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1      # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests
```

## Rules for tests

- Tests never call a real AI service and never need an API key. Use `FakeProvider`
  from `contextos.llm`, or set `CONTEXTOS_PROVIDER=fake`.
- Test chats are made up. Never commit a real export, even a small part of one. Real
  exports hold private messages, names and sometimes keys.
- Every test gets its own empty data folder (see `tests/conftest.py`), so no test
  touches your real `~/.contextos`.
- Do not add a new runtime dependency without asking first in an issue.

## How to add a new importer

An importer reads one tool's export and turns each chat into a `ConversationIn`. It does
not write to the database itself; `save_all()` does that, so every importer reports
results the same way and running an import twice never makes copies.

### 1. Make a small, made-up test export

Add a function to `tests/fixtures/make_fixtures.py` that writes a tiny export in the
tool's real file format: two or three short chats, plus the awkward cases you know of
(an empty chat, a broken one, an edited message). Call it from the `__main__` block at
the end of that file, then run the file to create the fixture:

```
python tests/fixtures/make_fixtures.py
```

### 2. Write the importer

Create `contextos/importers/<tool>.py` with one public function:

```python
from pathlib import Path

from contextos.importers.base import ImportFailed, ParsedExport, run_parser
from contextos.pack import Message
from contextos.store import ConversationIn

SOURCE = "mytool"  # the name shown in `contextos list`


def parse_conversation(raw: dict) -> ConversationIn:
    """One chat from the export. Raise ValueError with a short reason to skip it."""
    messages = [Message(role=m["role"], content=m["text"]) for m in raw.get("messages", [])]
    if not messages:
        raise ValueError("no messages")
    return ConversationIn(
        source_tool=SOURCE,
        source_id=str(raw["id"]),  # the tool's own ID, so re-imports update instead of copy
        title=raw.get("title"),
        messages=messages,
    )


def read_export(path: Path | str) -> ParsedExport:
    raw_items = ...  # read the file; raise ImportFailed with a clear message if you cannot
    return run_parser(raw_items, parse_conversation, title_key="title")
```

Useful helpers in `contextos/importers/base.py`:

- `load_json_lists(path, pattern, product)` reads a JSON list from a ZIP, a folder or a
  single file.
- `parse_epoch()` and `parse_iso()` turn the tool's dates into time-zone-aware dates.
- `cut(text)` shortens very long tool output.
- `run_parser()` calls your function for each chat and collects skipped chats with
  their reasons, so one bad chat never stops the whole import.

Keep only what helps a reader continue the work: the user's messages and the answers.
Leave out hidden thinking and large tool output. When the tool keeps several versions of
a chat (edits, retries), keep only the branch the user ended on.

### 3. Add the command

In `contextos/cli.py`, add a command next to the others and add the tool name to
`SOURCES`:

```python
@import_app.command("mytool")
def import_mytool(path: Annotated[Path, typer.Argument(help="The MyTool export file.")]) -> None:
    """Import an export from MyTool."""
    from contextos.importers import mytool

    _run_import("MyTool", lambda: mytool.read_export(path))
```

### 4. Test it

Create `tests/test_import_<tool>.py`. Look at `tests/test_import_chatgpt.py` for the
usual checks:

- each chat has the right title, ID, dates and messages in order;
- broken chats are skipped with a reason, and the rest still import;
- importing twice gives "0 new";
- `contextos import <tool> <fixture>` exits with code 0.

### 5. Document it

Add a short section to `README.md` under **Importing chats**: where to find the export
in the tool, the command, and what is kept or left out.

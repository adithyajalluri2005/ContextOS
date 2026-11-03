# ContextOS

**Move your AI conversations between tools, accounts and teammates.**

Export a chat from ChatGPT, Claude or a coding agent like Claude Code, turn it into a
short, portable *Context Pack*, and continue the work in any other AI tool. You can also
share the pack with your team.

> Status: early development. See `task_board.json` for the build plan.

## Planned first version

```
contextos import chatgpt export.zip      # official ChatGPT data export
contextos import claude-ai export.zip    # official Claude data export
contextos import claude-code             # local Claude Code sessions
contextos list
contextos pack <id> --out context.md     # paste this into your next chat
```

Later: an MCP server so AI tools can fetch packs themselves, a browser extension, and team sharing.

## Importing chats

### ChatGPT (works now)

1. In ChatGPT, open **Settings → Data controls → Export data** and confirm.
2. You get an email with a download link. Download the ZIP file.
3. Run:

   ```
   contextos import chatgpt path/to/export.zip
   ```

You can also pass the unzipped folder or `conversations.json`. Running it again later
only adds new chats and updates changed ones. When you edited a message or asked for a
new answer, only the version you ended on is kept. Images become `[image]`, and long
code-tool output is shortened.

### Claude.ai (works now)

1. In Claude, open **Settings → Privacy → Export data**.
2. You get an email with a download link. Download the ZIP file.
3. Run:

   ```
   contextos import claude-ai path/to/export.zip
   ```

The same rules apply: running it again does not make copies, and only the branch you
ended on is kept. Text from attached files is kept (shortened if very long). Claude's
hidden thinking and raw tool results are left out; a tool call shows as `[used tool: name]`.

## The Context Pack format

A pack is plain JSON with a title, summary, decisions, open questions, next steps, key facts,
code, file references and the source chat. Read the full description in [SPEC.md](SPEC.md).
The schema is in [`schemas/context-pack.schema.json`](schemas/context-pack.schema.json);
`contextos schema` prints it.

## Where your data lives

Imported chats are stored only on your computer, in a SQLite file at
`~/.contextos/contextos.db`. Set the `CONTEXTOS_HOME` environment variable to use a
different folder. Nothing is uploaded anywhere.

## Development setup

Needs Python 3.12 or newer.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1      # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
contextos --version
python -m pytest tests
```

## License

MIT

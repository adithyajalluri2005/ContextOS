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

## The Context Pack format

A pack is plain JSON with a title, summary, decisions, open questions, next steps, key facts,
code, file references and the source chat. Read the full description in [SPEC.md](SPEC.md).
The schema is in [`schemas/context-pack.schema.json`](schemas/context-pack.schema.json);
`contextos schema` prints it.

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

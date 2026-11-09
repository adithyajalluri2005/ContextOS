# ContextOS

**Save the context of one AI chat and load it in another.**

You tell the AI agent in chat A to save the context. It sends a short summary of the
work to ContextOS, a small MCP server on your computer. Later, in chat B (the same tool
or another one), you ask the agent to load that context, and it continues the work.
Nothing leaves your computer.

> Status: early development. The project was restarted on 2026-11-09. Right now only
> the command skeleton exists (`contextos --version`).

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

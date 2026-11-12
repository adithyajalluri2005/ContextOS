# ContextOS

**Save the context of one AI chat and load it in another.**

You are deep in a chat with an AI agent and want to continue somewhere else: a new chat,
another AI tool, or another agent. Tell the agent *"save this context to contextos"*.
It writes a short summary of the work (goal, where it stands, decisions, next steps,
files, code) and sends it to ContextOS, a small MCP server on your computer.

In the next chat, say *"load my last context from contextos"*. The agent there gets the
summary and continues the work.

```
Chat A (Claude Code)                     Chat B (Cursor, Claude Desktop, a new chat ...)
  you: "save this context"                 you: "load my last context"
  agent --save_context--> ContextOS  --load_context--> agent
                          (on your computer)
```

- **Nothing leaves your computer.** Contexts are kept in one local file.
- **No API key and no export files.** The agent you are talking to writes the summary.
- **You decide.** The agent saves or loads only when you ask.
- **Secrets are hidden** before anything is saved.

> Status: early development. MCP (Model Context Protocol) is the standard way AI tools
> connect to helper programs on your computer.

## Install

Needs Python 3.12 or newer. ContextOS is not on PyPI yet, so install it from this folder:

```powershell
git clone https://github.com/adithyajalluri2005/ContextOS.git
cd ContextOS
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -e ".[mcp]"
contextos --version
```

Your AI tool must start the program by its full path. Find it with:

```powershell
(Get-Command contextos).Source        # Windows, for example D:\ContextOS\.venv\Scripts\contextos.exe
which contextos                       # macOS/Linux
```

Below, replace `CONTEXTOS_PATH` with that path.

## Connect your AI tools

Add ContextOS to every tool you want to move work between. They all share the same
saved contexts.

### Claude Code

```
claude mcp add --scope user contextos -- CONTEXTOS_PATH mcp
```

`--scope user` makes it work in all your projects. Check it with `claude mcp list`.

### Claude Desktop

Open **Settings → Developer → Edit Config**. This opens `claude_desktop_config.json`.
Add:

```json
{
  "mcpServers": {
    "contextos": {
      "command": "CONTEXTOS_PATH",
      "args": ["mcp"]
    }
  }
}
```

On Windows, write the path with double backslashes, for example
`"D:\\ContextOS\\.venv\\Scripts\\contextos.exe"`. Restart Claude Desktop.

### Cursor

Open `~/.cursor/mcp.json` (all projects) or `.cursor/mcp.json` in one project, and add
the same `mcpServers` block as for Claude Desktop.

### Other tools

Any tool that can start a local MCP server over stdio works. The command is
`CONTEXTOS_PATH` with the argument `mcp`.

### claude.ai and ChatGPT (websites)

The websites cannot start a program on your computer. They can only reach an MCP server
on the internet. `contextos serve` runs ContextOS as a small web server on your computer,
and a tunnel such as [ngrok](https://ngrok.com) gives it a public address.

**Protection is a secret link.** The only address that works is
`https://<your-address>/<secret>/mcp`. Every other address answers "not found". The secret
is a long random code, made on first run and kept in `secret.txt` next to the database.
Anyone who has the full link can read and change all your contexts, so keep it private.

1. Get a fixed address. A free ngrok account includes one, shown in the ngrok dashboard
   under **Domains**, for example `your-name.ngrok-free.dev`. It does not change.
2. Start ContextOS, with your address:

   ```
   contextos serve --public-host your-name.ngrok-free.dev
   ```

   It prints the link to use, `https://your-name.ngrok-free.dev/<secret>/mcp`.
3. In a second terminal, start the tunnel to the same port (8765 by default):

   ```
   ngrok http --url=your-name.ngrok-free.dev 8765
   ```

4. Add the link as a custom connector: in claude.ai under **Settings → Connectors → Add
   custom connector**; in ChatGPT under **Settings → Apps & Connectors** (custom connectors
   may need **Developer mode** turned on). Menu names change from time to time.

Good to know:

- It works only while your computer is on and both programs run.
- The link stays the same after a restart. To change it (for example if someone saw it),
  run `contextos serve --new-secret ...`, then update the connector with the new link.
- `CONTEXTOS_SECRET` set in the environment is used instead of `secret.txt`.
- ContextOS listens on `127.0.0.1` only and writes no request logs, so the secret is not
  written to a log. The tunnel company (ngrok) handles your traffic and can see it.
- The websites and your local apps (Claude Code, Claude Desktop) share the same saved
  contexts.

## Use it

**Save**, in the chat you want to leave:

> Save this context to contextos.

The agent answers with an id and title, for example *"Saved as 3: Move blog to Hugo"*.

**Load**, in the new chat:

> Load my last context from contextos.

> Find my contextos context about the blog and continue.

The agent tells you in a line or two what the work is and the next step, then continues.

The agent can use four tools:

| Tool | What it does |
| --- | --- |
| `save_context` | Saves the context of the current chat. Returns the new id. |
| `list_contexts` | Saved contexts, newest first. Optional `source_tool` and `limit`. |
| `search_contexts` | Contexts that contain every word of `query`. |
| `load_context` | One context as Markdown (or `json`). Without an `id` it loads the newest. |

You can also look at your saved contexts yourself, in a terminal:

```
contextos list                 # newest first; --limit 5, --source claude-code
contextos show 3               # one context as Markdown; add --json for JSON
contextos delete 3             # asks first; add --yes to skip the question
```

## What a context holds

| Field | Meaning |
| --- | --- |
| `title`, `summary` | Required. The name of the work, and where it stands now. |
| `decisions` | Choices made, with reasons, and options that were rejected. |
| `open_questions` | Things still to decide. |
| `next_steps` | What to do next, in order. |
| `key_facts` | Versions, settings, error messages, and what was tried and failed. |
| `files` | Files that matter, each with a path and a note. |
| `code` | Short, important code. |
| `source_tool`, `project_dir` | Where the work happened. |

## Hidden secrets

Before a context is saved, ContextOS hides API keys (Anthropic, OpenAI, AWS, GitHub),
private keys, passwords inside URLs, email addresses and phone numbers. Each one becomes
a marker such as `[hidden: email]`. Only the number hidden of each kind is kept, never
the secret itself. The loaded context tells the next agent that something was hidden.

## Where your data lives

All contexts are in one SQLite file: `~/.contextos/contextos.db`. Set the
`CONTEXTOS_HOME` environment variable to use another folder. To start fresh, delete
the file.

## Limits

- **Websites:** claude.ai and chatgpt.com need `contextos serve` and a tunnel (see above),
  and your computer must be on. Protection is a secret link only, not a login.
- The quality of a context depends on the agent that writes it. ContextOS tells the agent
  what a good context holds, but it cannot check that the summary is right.
- Files and code in a context show the state at saving time. The loading agent is told to
  check them before changing anything.

## Development

```powershell
pip install -e ".[dev]"
python -m pytest tests
```

Tests use only made-up data and never call an AI service.

The first version of ContextOS imported chat export files and summarized them with a
separate AI model. It is kept at the git tag `v0-export-design`.

## License

MIT

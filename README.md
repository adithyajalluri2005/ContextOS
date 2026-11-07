# ContextOS

**Move your AI conversations between tools, accounts and teammates.**

Export a chat from ChatGPT, Claude or Claude Code, turn it into a short, portable
*Context Pack*, and continue the work in any other AI tool. You can also share the
pack with your team.

> Status: early development. Everything below works today.

## 30-second demo

No account and no API key needed. This uses a small made-up ChatGPT export that comes
with the repository, and the `fake` provider, which answers without calling any AI.

```powershell
pip install -e .
$env:CONTEXTOS_HOME = "$PWD\demo-home"     # keep the demo away from your real data
$env:CONTEXTOS_PROVIDER = "fake"
contextos import chatgpt tests/fixtures/chatgpt_export.zip
contextos list
contextos pack 1 --out context.md
```

On macOS or Linux, set the two variables with `export CONTEXTOS_HOME=$PWD/demo-home`
and `export CONTEXTOS_PROVIDER=fake`.

The import says it skipped 2 chats: the test export holds broken chats on purpose.
`contextos list` shows the imported chats with their IDs, and `context.md` is a pack you
could paste into a new chat. Delete the `demo-home` folder when you are done. With the fake provider the summary is only a placeholder.
For a real one, pick an AI model (see [Choosing an AI model](#choosing-an-ai-model)) and
import your own export.

## Everyday use

```
contextos import chatgpt export.zip        # or: claude-ai export.zip, or: claude-code
contextos list                             # find the chat you want
contextos pack <id> --out context.md       # paste context.md into your next chat
```

## Importing chats

### ChatGPT

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

### Claude.ai

1. In Claude, open **Settings → Privacy → Export data**.
2. You get an email with a download link. Download the ZIP file.
3. Run:

   ```
   contextos import claude-ai path/to/export.zip
   ```

The same rules apply: running it again does not make copies, and only the branch you
ended on is kept. Text from attached files is kept (shortened if very long). Claude's
hidden thinking and raw tool results are left out; a tool call shows as `[used tool: name]`.

### Claude Code

Claude Code already saves every session on your computer, so there is nothing to export:

```
contextos import claude-code                       # all sessions in ~/.claude/projects
contextos import claude-code --path <folder|file>  # one project folder or one .jsonl file
```

Each session keeps your prompts, Claude's answers, the working folder and git branch,
and one short line per tool call, such as `[ran: pytest -q]` or `[edited file: app.py]`.
Tool output, hidden thinking, helper-agent messages and status messages are left out.
If you rewound a session, only the branch you ended on is kept. If it was compacted, the
full history is kept, with a note where compaction happened.

Known limit: when Claude runs several tools at once, a few of those tool lines can be
missing. Your prompts and Claude's answers are never lost.

Want another tool? See [CONTRIBUTING.md](CONTRIBUTING.md#how-to-add-a-new-importer).

## Looking at your chats

```
contextos list                        # every imported chat, newest first
contextos list --source claude-code   # only one tool: chatgpt, claude-ai or claude-code
contextos show <id>                   # print one chat, using the ID from the list
```

The list shows the ID, the tool it came from, the date of the last change, the number of
messages and the title. All dates and times are shown in UTC.

## Making a Context Pack

```
contextos pack <id> --out context.md                 # Markdown to paste into a new chat
contextos pack <id> --format json -o pack.json       # the pack as data
contextos pack <id> --format claude-md >> CLAUDE.md  # a section for CLAUDE.md or AGENTS.md
```

Without `--out` the pack is printed to the screen; progress messages go to stderr, so
you can send the output straight into a file. Add `--with-transcript` to include the
full conversation as well. The `claude-md` section starts with `<!-- contextos:start -->`
and ends with `<!-- contextos:end -->`, so you can find it and replace it later.

Long chats are summarized in parts, and the part summaries are then combined into one pack.

### Hiding secrets

Before the chat is sent to the AI model, ContextOS hides API keys (OpenAI, Anthropic,
AWS, GitHub), private keys, passwords inside URLs, email addresses and phone numbers.
Each one becomes a marker such as `[hidden: email]`. The finished pack is checked again
before it is written. The pack records only how many items of each kind were hidden
(the `redacted` field), never the hidden text.

`--no-redact` turns this off and prints a warning. Use it only for chats you are sure
are safe to share.

## Choosing an AI model

A Context Pack is written by an AI model. Pick one with environment variables
(see `.env.example`):

| `CONTEXTOS_PROVIDER` | Install | Key | Default model |
| --- | --- | --- | --- |
| `anthropic` | `pip install "contextos[anthropic]"` | `ANTHROPIC_API_KEY` | `claude-opus-5-5` |
| `openai` | `pip install "contextos[openai]"` | `OPENAI_API_KEY` | `gpt-5` |
| `ollama` | nothing extra; Ollama must be running | none | `llama3.1` |
| `fake` | nothing | none | answers without any AI, for tests and the demo |

Set `CONTEXTOS_MODEL` to use another model. Keys are read only from environment
variables and are never saved. Your chat text (with secrets hidden) is sent to the
provider you choose; with Ollama it stays on your computer.

## Using ContextOS from AI tools (MCP)

ContextOS can run as an MCP server, so an AI app or coding agent can find your chats and
fetch packs by itself. MCP (Model Context Protocol) is the standard way AI tools connect
to local helper programs.

```
pip install "contextos[mcp]"
contextos mcp          # the AI tool starts this for you; it talks over stdin/stdout
```

It offers three tools:

| Tool | What it does |
| --- | --- |
| `list_conversations` | Imported chats, newest first. Optional `source` and `limit`. |
| `search` | Chats that contain every word of `query`, with a short piece of matching text. |
| `get_context_pack` | A pack for one chat `id`, as `markdown` (default), `json` or `claude-md`. |

It uses the same database and the same AI model settings as the command line, so set
`CONTEXTOS_PROVIDER` (and a key, if needed) in the server's environment. Secrets are
always hidden here, also in titles and search results. To add it to Claude Code:

```
claude mcp add contextos -e CONTEXTOS_PROVIDER=anthropic -e ANTHROPIC_API_KEY=... -- contextos mcp
```

Other apps take the same command (`contextos mcp`) in their MCP settings.

## The Context Pack format

A pack is plain JSON with a title, summary, decisions, open questions, next steps, key facts,
code, file references and the source chat. Read the full description in [SPEC.md](SPEC.md).
The schema is in [`schemas/context-pack.schema.json`](schemas/context-pack.schema.json);
`contextos schema` prints it.

## Where your data lives

Imported chats are stored only on your computer, in a SQLite file at
`~/.contextos/contextos.db`. Set the `CONTEXTOS_HOME` environment variable to use a
different folder. Nothing is uploaded, except the chat text sent to the AI provider you
choose when you make a pack.

## Development setup

Needs Python 3.12 or newer.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1      # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
contextos --version
python -m pytest tests
```

Tests never call a real AI service. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT

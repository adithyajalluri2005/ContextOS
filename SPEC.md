# Context Pack format — version 0.1

A **Context Pack** is a short, portable summary of one AI conversation. It lets you
continue the work in another chat, another AI tool, or hand it to a teammate.

It is plain JSON, so any program can read and write it. ContextOS can also turn a
pack into Markdown, ready to paste into a new chat.

- Machine-readable schema: [`schemas/context-pack.schema.json`](schemas/context-pack.schema.json) (JSON Schema 2020-12)
- Reference code: [`contextos/pack/model.py`](contextos/pack/model.py)
- Make the schema again with: `contextos schema --out schemas/context-pack.schema.json`

Status: **draft**. Fields may still change before version 1.0.

## Design rules

1. **Small first.** A pack should fit easily into a new chat. The full transcript is optional.
2. **No vendor lock-in.** Nothing in the format depends on one AI company or tool.
3. **Readable by people.** Every field is plain text a human can check before sharing.
4. **Strict.** Unknown fields are rejected, so spelling mistakes are caught early.

## Fields

### Top level

| Field | Type | Required | Meaning |
|---|---|---|---|
| `spec_version` | `"0.1"` | no (default `"0.1"`) | Version of this format. |
| `title` | string | **yes** | Short name for what the conversation is about. |
| `summary` | string | **yes** | A few sentences a new reader needs first. |
| `decisions` | list of [Decision](#decision) | no | What was decided, and why. |
| `open_questions` | list of strings | no | Questions not yet answered. |
| `next_steps` | list of strings | no | Concrete things to do next. |
| `key_facts` | list of strings | no | Facts to keep: names, versions, limits, numbers. |
| `code_snippets` | list of [CodeSnippet](#codesnippet) | no | Code worth carrying over. |
| `file_refs` | list of [FileRef](#fileref) | no | Files the conversation talked about. |
| `source` | [Source](#source) | **yes** | Where the conversation came from. |
| `created_at` | date-time | no (default: now) | When this pack was made. |
| `raw_transcript` | list of [Message](#message) | no | The full conversation. Leave out to keep the pack small. |

Text values are trimmed. `title`, `summary` and other required text must not be blank.

### Source

| Field | Type | Required | Meaning |
|---|---|---|---|
| `tool` | string | **yes** | Tool the chat came from, e.g. `chatgpt`, `claude-ai`, `claude-code`. |
| `conversation_id` | string | no | ID of the conversation in that tool. |
| `title` | string | no | Title of the original conversation. |
| `url` | string | no | Link to the original conversation. |
| `created_at` | date-time | no | When the conversation started. |
| `updated_at` | date-time | no | When it last changed. |

Use lowercase, dash-separated names for `tool`. Known values: `chatgpt`, `claude-ai`, `claude-code`.

### Decision

| Field | Type | Required |
|---|---|---|
| `decision` | string | **yes** |
| `reason` | string | no |

### CodeSnippet

| Field | Type | Required | Meaning |
|---|---|---|---|
| `code` | string | **yes** | The code. |
| `language` | string | no | e.g. `python`, `shell`. |
| `path` | string | no | File the code belongs to. |
| `description` | string | no | What it does or why it matters. |

### FileRef

| Field | Type | Required |
|---|---|---|
| `path` | string | **yes** |
| `description` | string | no |

### Message

| Field | Type | Required | Meaning |
|---|---|---|---|
| `role` | `user` \| `assistant` \| `system` \| `tool` | **yes** | Who wrote it. |
| `content` | string | **yes** | The text. |
| `created_at` | date-time | no | When it was sent. |

## Dates

All dates use ISO 8601 and **must include a time zone**, for example
`2026-11-03T08:00:00Z` or `2026-11-03T13:30:00+05:30`. Dates without a time zone
are rejected, because the same chat is often shared across countries.

## Example

```json
{
  "spec_version": "0.1",
  "title": "Build plan for ContextOS",
  "summary": "We planned a tool that moves AI chats between tools. Stage 1 is a command-line tool.",
  "decisions": [
    { "decision": "Start with a command-line tool", "reason": "Proves the idea with no server" }
  ],
  "open_questions": ["Which browser should the extension support first?"],
  "next_steps": ["Write the ChatGPT importer"],
  "key_facts": ["Python 3.12", "License is MIT"],
  "code_snippets": [
    { "code": "contextos pack 42 --out context.md", "language": "shell" }
  ],
  "file_refs": [{ "path": "contextos/cli.py", "description": "Command entry point" }],
  "source": {
    "tool": "claude-ai",
    "conversation_id": "abc-123",
    "created_at": "2026-11-01T10:00:00Z"
  },
  "created_at": "2026-11-03T08:00:00Z"
}
```

## Versioning

- `spec_version` changes when the format changes.
- Before 1.0, any version may change fields. A reader should reject versions it does not know.
- From 1.0 on, new optional fields raise the minor number (1.1). Removing or renaming a field raises the major number (2.0).

## Privacy

Packs are made to be shared. Before you share one, check it for API keys, passwords
and personal data. ContextOS will hide common secrets automatically (planned in T-010).

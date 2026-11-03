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

## License

MIT

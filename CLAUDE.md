@AGENTS.md

## ContextOS workbench rules

- Stack: Python 3.12 package `contextos/` (Typer command line, Pydantic models, SQLite storage). Tests in `tests/`. No server or frontend in Stage 1.
- Python: always use the repo venv (`.\.venv\Scripts\Activate.ps1`).
- Tests must never call a real AI service or need an API key. Use the FakeProvider and files in `tests/fixtures/`. Test chats must be made up, never real exports.
- Session start: `python scripts/init_agent.py`, then read `agent_state.json` and the active task in `task_board.json`.
- Run every acceptance command through the feedback runner so the check can see it, exactly as written in the scope contract. Put `--` before the command so its own flags are passed through, for example:
  - `python scripts/run_with_feedback.py --timeout 300 -- python -m pytest tests`
- Each task needs `outputs/scope/closed/<task_id>.json` with `acceptance_criteria`. If the file is missing, the check has nothing to test and passes by mistake. Do not start a task without it.
- A task is done only when `python scripts/verify_agent.py <task_id>` exits 0.
- Session end: `python scripts/generate_handoff.py <task_id>` and update `agent_state.json`.
- Never read or print `.env`; use `.env.example` for reference.

Every chat reply, report, summary, question and next-step box is for a human reader: write simple, plain English that a non-native reader understands at first read. Never use AI-agent or engineering slang (for example "load-bearing", "cutover", "ship", "gate", "wire up", "spin up", "happy path", "TL;DR"). If a technical term is truly needed, explain it in plain words the first time.

Messages between agents (prompts, briefs, agent-to-agent notes) are exempt.

"""Turn a stored conversation into a Context Pack with the help of an AI model.

Short chats go to the model in one request. Long chats are cut into parts on
message boundaries; the model writes notes for each part, and the notes are
then merged (in rounds, if there are many) into one pack.

The model answers with a "draft": the pack fields it can fill. The builder
adds what it already knows (source, dates, optional transcript) itself.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from datetime import timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from contextos.llm import Provider
from contextos.pack.model import CodeSnippet, ContextPack, Decision, FileRef, Message, Source
from contextos.store import Conversation

UNTITLED = "Untitled conversation"
# Room kept for the instructions around the transcript in each request.
PROMPT_OVERHEAD_CHARS = 4_000
MIN_PART_CHARS = 1_000
ATTEMPTS = 2  # one retry when the answer is not valid JSON

Progress = Callable[[str], None]


class PackBuildError(RuntimeError):
    """The pack could not be built (empty chat, or the model never gave a usable answer)."""


# --- what the model must answer ---------------------------------------------

_TEXT = {"type": "string"}
_TEXT_LIST = {"type": "array", "items": _TEXT}


def _object(**props: Any) -> dict[str, Any]:
    # Every field required and no extras: the strictest providers demand this form.
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


DRAFT_SCHEMA: dict[str, Any] = _object(
    title=_TEXT,
    summary=_TEXT,
    decisions={"type": "array", "items": _object(decision=_TEXT, reason=_TEXT)},
    open_questions=_TEXT_LIST,
    next_steps=_TEXT_LIST,
    key_facts=_TEXT_LIST,
    code_snippets={
        "type": "array",
        "items": _object(code=_TEXT, language=_TEXT, path=_TEXT, description=_TEXT),
    },
    file_refs={"type": "array", "items": _object(path=_TEXT, description=_TEXT)},
)

SYSTEM_PROMPT = """\
You write Context Packs: short handover notes that let a person, or another AI \
assistant, continue a conversation in a new chat without reading the old one.

Rules:
- Use only what the conversation says. Never invent facts, names, numbers or code.
- Keep what the next chat needs; leave out greetings, small talk and dead ends.
- When something changed during the chat, keep only the latest state.
- Write plainly and briefly, in the language of the conversation.
- Answer with one JSON object and nothing else. Use "" for unknown text fields.

Fields:
- title: a short name for what the conversation is about.
- summary: 2 to 5 sentences: the goal, what was done, and where it stands now.
- decisions: what was decided, each with the reason if one was given.
- open_questions: questions that are still not answered.
- next_steps: concrete things still to do.
- key_facts: facts worth keeping: names, versions, numbers, limits, settings.
- code_snippets: only code the next chat really needs, copied exactly, with \
language, file path and a one-line description where known.
- file_refs: files that were discussed, each with why it matters.
"""

PART_PROMPT = """\
This is part {index} of {count} of one long conversation. Write notes for this \
part only, in the JSON form described. Earlier and later parts are handled \
separately, so do not guess what happens outside this part.

<conversation_part>
{text}
</conversation_part>"""

WHOLE_PROMPT = """\
Write the Context Pack for this conversation.

<conversation>
{text}
</conversation>"""

COMBINE_PROMPT = """\
Below are notes on {count} consecutive parts of one conversation, oldest first. \
Merge them into one Context Pack in the same JSON form. Later parts win when \
they disagree: drop questions that were answered later, steps that were done \
later, and decisions that were changed. Remove repeats.

<notes>
{text}
</notes>"""

RETRY_NOTE = "\n\nYour last answer could not be used ({error}). Answer again with only the JSON object."


# --- reading the model's answer ---------------------------------------------


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class PackDraft(BaseModel):
    """The model's answer, read leniently: wrong shapes are fixed, empty items dropped."""

    model_config = ConfigDict(extra="ignore")

    title: str | None = None
    summary: str | None = None
    decisions: list[Decision] = []
    open_questions: list[str] = []
    next_steps: list[str] = []
    key_facts: list[str] = []
    code_snippets: list[CodeSnippet] = []
    file_refs: list[FileRef] = []

    @field_validator("title", "summary", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str | None:
        return _clean(value)

    @field_validator("open_questions", "next_steps", "key_facts", mode="before")
    @classmethod
    def _texts(cls, value: Any) -> list[str]:
        seen: dict[str, None] = {}
        for item in _as_list(value):
            text = _clean(item)
            if text:
                seen.setdefault(text, None)
        return list(seen)

    @field_validator("decisions", mode="before")
    @classmethod
    def _decisions(cls, value: Any) -> list[dict]:
        out = []
        for item in _as_list(value):
            if isinstance(item, dict):
                decision, reason = _clean(item.get("decision")), _clean(item.get("reason"))
            else:
                decision, reason = _clean(item), None
            if decision:
                out.append({"decision": decision, "reason": reason})
        return out

    @field_validator("code_snippets", mode="before")
    @classmethod
    def _snippets(cls, value: Any) -> list[dict]:
        out = []
        for item in _as_list(value):
            if isinstance(item, dict) and str(item.get("code") or "").strip():
                out.append({
                    "code": str(item["code"]).strip("\n"),
                    **{k: _clean(item.get(k)) for k in ("language", "path", "description")},
                })
        return out

    @field_validator("file_refs", mode="before")
    @classmethod
    def _files(cls, value: Any) -> list[dict]:
        out = []
        for item in _as_list(value):
            if isinstance(item, dict):
                path, description = _clean(item.get("path")), _clean(item.get("description"))
            else:
                path, description = _clean(item), None
            if path:
                out.append({"path": path, "description": description})
        return out


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


_FENCE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n(.*?)\n?```\s*$", re.DOTALL)


def parse_draft(text: str) -> PackDraft:
    """Read a draft from the model's answer. Raises ValueError if it cannot be used."""
    raw = text.strip()
    fenced = _FENCE.match(raw)
    if fenced:
        raw = fenced.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("the answer is not JSON") from None
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"the answer is not valid JSON: {exc.msg}") from None
    if not isinstance(data, dict):
        raise ValueError("the answer is not a JSON object")
    try:
        draft = PackDraft.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"the answer has the wrong shape: {exc.errors()[0]['msg']}") from None
    if not draft.summary:
        raise ValueError("the summary is empty")
    return draft


# --- cutting a chat into parts -----------------------------------------------


def render_message(position: int, message: Message) -> str:
    stamp = ""
    if message.created_at:
        stamp = " (" + message.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") + ")"
    return f"[{position}] {message.role.upper()}{stamp}:\n{message.content.strip()}"


def split_parts(messages: Sequence[Message], max_chars: int) -> list[str]:
    """Group rendered messages into parts of at most `max_chars`, keeping message order.

    A message longer than `max_chars` on its own is cut into pieces, marked as continued.
    """
    blocks: list[str] = []
    for pos, msg in enumerate(messages, start=1):
        if not msg.content.strip():
            continue
        block = render_message(pos, msg)
        if len(block) <= max_chars:
            blocks.append(block)
            continue
        marker = f"[{pos}] (continued)\n"
        step = max_chars - len(marker)
        blocks.append(block[:max_chars])
        rest = block[max_chars:]
        while rest:
            blocks.append(marker + rest[:step])
            rest = rest[step:]

    parts: list[str] = []
    current: list[str] = []
    size = 0
    for block in blocks:
        extra = len(block) + (2 if current else 0)  # blank line between messages
        if current and size + extra > max_chars:
            parts.append("\n\n".join(current))
            current, size = [], 0
            extra = len(block)
        current.append(block)
        size += extra
    if current:
        parts.append("\n\n".join(current))
    return parts


# --- building ----------------------------------------------------------------


class PackBuilder:
    def __init__(self, provider: Provider, *, max_chars: int | None = None, progress: Progress | None = None) -> None:
        self.provider = provider
        limit = max_chars if max_chars is not None else provider.max_input_chars - PROMPT_OVERHEAD_CHARS
        self.max_chars = max(limit, MIN_PART_CHARS)
        self._progress = progress or (lambda _msg: None)

    def _ask(self, prompt: str) -> PackDraft:
        error = ""
        for _ in range(ATTEMPTS):
            answer = self.provider.complete(SYSTEM_PROMPT, prompt + (RETRY_NOTE.format(error=error) if error else ""),
                                            schema=DRAFT_SCHEMA)
            try:
                return parse_draft(answer)
            except ValueError as exc:
                error = str(exc)
        raise PackBuildError(f"The model did not give a usable answer after {ATTEMPTS} tries: {error}.")

    def draft(self, messages: Sequence[Message]) -> PackDraft:
        parts = split_parts(messages, self.max_chars)
        if not parts:
            raise PackBuildError("The conversation has no messages to summarize.")
        if len(parts) == 1:
            self._progress("Summarizing the conversation")
            return self._ask(WHOLE_PROMPT.format(text=parts[0]))

        notes = []
        for i, part in enumerate(parts, start=1):
            self._progress(f"Summarizing part {i} of {len(parts)}")
            notes.append(self._ask(PART_PROMPT.format(index=i, count=len(parts), text=part)))
        return self._merge(notes)

    def _merge(self, notes: list[PackDraft]) -> PackDraft:
        """Merge notes in rounds until one draft is left. Each round at least halves the count."""
        round_no = 0
        while True:
            round_no += 1
            groups = self._group(notes)
            if len(groups) == 1:
                self._progress("Combining the part summaries")
                return self._combine(groups[0])
            self._progress(f"Combining part summaries, round {round_no} ({len(notes)} to {len(groups)})")
            notes = [self._combine(group) for group in groups]

    def _group(self, notes: list[PackDraft]) -> list[list[PackDraft]]:
        """Consecutive groups that fit in one request. Each group holds at least two notes,
        so every round makes progress even if single notes are large."""
        groups: list[list[PackDraft]] = []
        current: list[PackDraft] = []
        size = 0
        for note in notes:
            length = len(_note_text(note, 0)) + 2
            if len(current) >= 2 and size + length > self.max_chars:
                groups.append(current)
                current, size = [], 0
            current.append(note)
            size += length
        if current:
            if len(current) == 1 and groups:
                groups[-1].append(current[0])
            else:
                groups.append(current)
        return groups

    def _combine(self, group: list[PackDraft]) -> PackDraft:
        text = "\n\n".join(_note_text(note, i) for i, note in enumerate(group, start=1))
        return self._ask(COMBINE_PROMPT.format(count=len(group), text=text))

    def build(self, conversation: Conversation, *, include_transcript: bool = False) -> ContextPack:
        draft = self.draft(conversation.messages)
        return ContextPack(
            title=draft.title or conversation.title or UNTITLED,
            summary=draft.summary,
            decisions=draft.decisions,
            open_questions=draft.open_questions,
            next_steps=draft.next_steps,
            key_facts=draft.key_facts,
            code_snippets=draft.code_snippets,
            file_refs=draft.file_refs,
            source=Source(
                tool=conversation.source_tool,
                conversation_id=conversation.source_id,
                title=conversation.title,
                url=conversation.url,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
            ),
            raw_transcript=list(conversation.messages) if include_transcript else None,
        )


def _note_text(note: PackDraft, index: int) -> str:
    body = note.model_dump_json(exclude_none=True)
    return f"<part_notes index=\"{index}\">\n{body}\n</part_notes>"


def build_pack(
    conversation: Conversation,
    provider: Provider,
    *,
    include_transcript: bool = False,
    max_chars: int | None = None,
    progress: Progress | None = None,
) -> ContextPack:
    """Build a Context Pack for `conversation` using `provider`."""
    builder = PackBuilder(provider, max_chars=max_chars, progress=progress)
    return builder.build(conversation, include_transcript=include_transcript)


__all__ = ["DRAFT_SCHEMA", "PackBuildError", "PackBuilder", "PackDraft", "build_pack", "parse_draft", "split_parts"]

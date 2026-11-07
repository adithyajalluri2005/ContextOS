"""Provider layer and pack builder. No test calls a real AI service: clients and HTTP are stand-ins."""

import io
import json
import sys
import urllib.error
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from contextos.llm import FakeProvider, ProviderError, get_provider
from contextos.llm.anthropic_provider import FALLBACK_BETA, AnthropicProvider
from contextos.llm.fake import default_answer
from contextos.llm.ollama_provider import OllamaProvider, normalize_host
from contextos.llm.openai_provider import OpenAIProvider
from contextos.pack import ContextPack, Message
from contextos.pack.builder import (
    DRAFT_SCHEMA,
    SYSTEM_PROMPT,
    PackBuildError,
    build_pack,
    parse_draft,
    split_parts,
)
from contextos.store import Conversation

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)


def conversation(messages, **overrides):
    fields = dict(
        id=1,
        source_tool="chatgpt",
        source_id="conv-1",
        title="Pick a database",
        url="https://chatgpt.com/c/conv-1",
        created_at=T0,
        updated_at=datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc),
        imported_at=T0,
        message_count=len(messages),
        messages=messages,
    )
    fields.update(overrides)
    return Conversation(**fields)


SHORT_CHAT = [
    Message(role="user", content="Should we use SQLite or Postgres for the local tool?", created_at=T0),
    Message(role="assistant", content="SQLite: one file, no server, enough for one user."),
    Message(role="user", content="OK, SQLite it is. Where do we keep the file?"),
]

DRAFT = {
    "title": "Database choice",
    "summary": "Picked SQLite for the local tool. The file location is still open.",
    "decisions": [{"decision": "Use SQLite", "reason": "One file, no server."}],
    "open_questions": ["Where should the database file live?"],
    "next_steps": ["Write the storage module."],
    "key_facts": ["Single user tool."],
    "code_snippets": [],
    "file_refs": [{"path": "contextos/store.py", "description": "Storage module."}],
}


def numbered_chat(count, size=200):
    return [
        Message(role="user" if i % 2 == 0 else "assistant", content=f"message-{i:03d} " + "x" * size)
        for i in range(count)
    ]


# --- choosing a provider ------------------------------------------------------


def test_no_provider_chosen_explains_what_to_set():
    with pytest.raises(ProviderError, match="Set CONTEXTOS_PROVIDER to one of: anthropic, openai, ollama, fake"):
        get_provider(env={})


def test_unknown_provider_lists_choices():
    with pytest.raises(ProviderError, match="Unknown AI provider 'gemini'"):
        get_provider(env={"CONTEXTOS_PROVIDER": "gemini"})


def test_provider_and_model_come_from_environment():
    provider = get_provider(env={"CONTEXTOS_PROVIDER": " Ollama ", "CONTEXTOS_MODEL": "qwen3", "OLLAMA_HOST": ""})
    assert isinstance(provider, OllamaProvider)
    assert provider.model == "qwen3"

    fake = get_provider(env={"CONTEXTOS_PROVIDER": "fake"})
    assert isinstance(fake, FakeProvider)


def test_arguments_override_environment():
    provider = get_provider("fake", model="m2", env={"CONTEXTOS_PROVIDER": "anthropic", "CONTEXTOS_MODEL": "m1"})
    assert isinstance(provider, FakeProvider)
    assert provider.model == "m2"


def test_reads_os_environment_by_default(monkeypatch):
    monkeypatch.setenv("CONTEXTOS_PROVIDER", "fake")
    monkeypatch.delenv("CONTEXTOS_MODEL", raising=False)
    assert isinstance(get_provider(), FakeProvider)


@pytest.mark.parametrize(("name", "key"), [("anthropic", "ANTHROPIC_API_KEY"), ("openai", "OPENAI_API_KEY")])
def test_missing_key_names_the_variable(monkeypatch, name, key):
    monkeypatch.delenv(key, raising=False)
    with pytest.raises(ProviderError, match=f"{key} is not set"):
        get_provider(name, env={})


@pytest.mark.parametrize(
    ("name", "key", "module", "extra"),
    [
        ("anthropic", "ANTHROPIC_API_KEY", "anthropic", "contextos[anthropic]"),
        ("openai", "OPENAI_API_KEY", "openai", "contextos[openai]"),
    ],
)
def test_missing_package_says_how_to_install(monkeypatch, name, key, module, extra):
    monkeypatch.setenv(key, "test-key-not-real")
    monkeypatch.setitem(sys.modules, module, None)  # makes `import <module>` fail
    with pytest.raises(ProviderError, match=rf"pip install \"{extra.replace('[', r'\[').replace(']', r'\]')}\""):
        get_provider(name, env={})


@pytest.mark.parametrize(("name", "key", "module"), [
    ("anthropic", "ANTHROPIC_API_KEY", "anthropic"),
    ("openai", "OPENAI_API_KEY", "openai"),
])
def test_key_is_taken_from_environment(monkeypatch, name, key, module):
    pytest.importorskip(module)
    monkeypatch.setenv(key, "test-key-not-real")
    provider = get_provider(name, env={})
    assert provider._client.api_key == "test-key-not-real"  # client is built, no request is sent


# --- Anthropic ---------------------------------------------------------------


class RecordingClient:
    """Stands in for an SDK client: records the request and returns a prepared response."""

    def __init__(self, response):
        self.requests = []
        self.response = response
        create = lambda **kwargs: (self.requests.append(kwargs), self.response)[1]  # noqa: E731
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=create))
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))


def claude_response(*blocks, stop_reason="end_turn"):
    content = [SimpleNamespace(type=t, text=x) for t, x in blocks]
    return SimpleNamespace(content=content, stop_reason=stop_reason)


def test_anthropic_request_shape_and_text():
    client = RecordingClient(claude_response(("thinking", ""), ("text", '{"summary": '), ("text", '"ok"}')))
    provider = AnthropicProvider(client=client)
    assert provider.complete("SYS", "PROMPT", schema=DRAFT_SCHEMA) == '{"summary": "ok"}'

    req = client.requests[0]
    assert req["model"] == "claude-opus-5-5"
    assert req["system"] == "SYS"
    assert req["messages"] == [{"role": "user", "content": "PROMPT"}]
    assert req["output_config"] == {"effort": "medium", "format": {"type": "json_schema", "schema": DRAFT_SCHEMA}}
    assert req["fallbacks"] == "default"
    assert req["betas"] == [FALLBACK_BETA]
    assert "thinking" not in req and "temperature" not in req


def test_anthropic_older_model_gets_no_fallback_or_effort():
    client = RecordingClient(claude_response(("text", "hi")))
    AnthropicProvider("claude-haiku-4-5", client=client).complete("S", "P")
    req = client.requests[0]
    assert req["model"] == "claude-haiku-4-5"
    assert "fallbacks" not in req and "betas" not in req and "output_config" not in req


@pytest.mark.parametrize(("stop", "blocks", "message"), [
    ("refusal", [], "declined"),
    ("max_tokens", [("text", "{")], "cut off"),
    ("end_turn", [("text", "   ")], "empty answer"),
])
def test_anthropic_bad_answers_raise(stop, blocks, message):
    provider = AnthropicProvider(client=RecordingClient(claude_response(*blocks, stop_reason=stop)))
    with pytest.raises(ProviderError, match=message):
        provider.complete("S", "P")


def test_anthropic_api_error_becomes_provider_error():
    anthropic = pytest.importorskip("anthropic")

    def fail(**kwargs):
        raise anthropic.APIConnectionError(request=None)

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=fail)))
    with pytest.raises(ProviderError, match="Anthropic request failed"):
        AnthropicProvider(client=client).complete("S", "P")


# --- OpenAI ------------------------------------------------------------------


def openai_response(content, finish_reason="stop", refusal=None):
    message = SimpleNamespace(content=content, refusal=refusal)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)])


def test_openai_request_shape_and_text():
    client = RecordingClient(openai_response('{"summary": "ok"}'))
    provider = OpenAIProvider("gpt-test", client=client)
    assert provider.complete("SYS", "PROMPT", schema=DRAFT_SCHEMA) == '{"summary": "ok"}'
    req = client.requests[0]
    assert req["model"] == "gpt-test"
    assert req["messages"] == [{"role": "system", "content": "SYS"}, {"role": "user", "content": "PROMPT"}]
    assert req["response_format"]["type"] == "json_schema"
    assert req["response_format"]["json_schema"]["strict"] is True
    assert req["response_format"]["json_schema"]["schema"] == DRAFT_SCHEMA


@pytest.mark.parametrize(("response", "message"), [
    (openai_response(None, refusal="no"), "declined"),
    (openai_response("{", finish_reason="length"), "cut off"),
    (openai_response(""), "empty answer"),
    (SimpleNamespace(choices=[]), "no answer"),
])
def test_openai_bad_answers_raise(response, message):
    with pytest.raises(ProviderError, match=message):
        OpenAIProvider(client=RecordingClient(response)).complete("S", "P")


# --- Ollama ------------------------------------------------------------------


class FakeHTTPResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def recording_urlopen(answer):
    seen = []

    def urlopen(request, timeout):
        seen.append((request, timeout))
        if isinstance(answer, Exception):
            raise answer
        return FakeHTTPResponse(json.dumps(answer).encode())

    return urlopen, seen


@pytest.mark.parametrize(("raw", "expected"), [
    (None, "http://localhost:11434"),
    ("", "http://localhost:11434"),
    ("0.0.0.0:11434", "http://localhost:11434"),
    ("0.0.0.0", "http://localhost:11434"),
    ("gpu-box", "http://gpu-box:11434"),
    ("https://ollama.example.com:443/", "https://ollama.example.com:443"),
])
def test_ollama_host_forms(raw, expected):
    assert normalize_host(raw) == expected


def test_ollama_request_shape_and_text():
    urlopen, seen = recording_urlopen({"message": {"content": '{"summary": "ok"}'}, "done_reason": "stop"})
    provider = OllamaProvider("llama-test", host="box:1234", urlopen=urlopen)
    assert provider.complete("SYS", "PROMPT", schema=DRAFT_SCHEMA) == '{"summary": "ok"}'

    request, timeout = seen[0]
    assert request.full_url == "http://box:1234/api/chat"
    assert request.get_method() == "POST"
    body = json.loads(request.data)
    assert body["model"] == "llama-test"
    assert body["stream"] is False
    assert body["format"] == DRAFT_SCHEMA
    assert body["messages"][0] == {"role": "system", "content": "SYS"}
    assert timeout > 0


def test_ollama_unreachable_says_so():
    urlopen, _ = recording_urlopen(urllib.error.URLError("connection refused"))
    with pytest.raises(ProviderError, match="Could not reach Ollama at http://localhost:11434. Is it running"):
        OllamaProvider(host="", urlopen=urlopen).complete("S", "P")


def test_ollama_missing_model_says_how_to_pull():
    error = urllib.error.HTTPError("u", 404, "Not Found", {}, io.BytesIO(b'{"error": "model not found"}'))
    urlopen, _ = recording_urlopen(error)
    with pytest.raises(ProviderError, match="ollama pull llama-test"):
        OllamaProvider("llama-test", host="", urlopen=urlopen).complete("S", "P")


def test_ollama_server_error_shows_detail():
    error = urllib.error.HTTPError("u", 500, "Server Error", {}, io.BytesIO(b'{"error": "out of memory"}'))
    urlopen, _ = recording_urlopen(error)
    with pytest.raises(ProviderError, match=r"\(500\): out of memory"):
        OllamaProvider(host="", urlopen=urlopen).complete("S", "P")


def test_ollama_cut_off_answer_raises():
    urlopen, _ = recording_urlopen({"message": {"content": "{"}, "done_reason": "length"})
    with pytest.raises(ProviderError, match="cut off"):
        OllamaProvider(host="", urlopen=urlopen).complete("S", "P")


# --- FakeProvider -------------------------------------------------------------


def test_fake_provider_records_calls_and_uses_answers_in_order():
    fake = FakeProvider(["first", {"summary": "second"}])
    assert fake.complete("S", "P1", schema={"x": 1}) == "first"
    assert json.loads(fake.complete("S", "P2")) == {"summary": "second"}
    assert [c.prompt for c in fake.calls] == ["P1", "P2"]
    assert fake.calls[0].schema == {"x": 1}
    with pytest.raises(ProviderError, match="ran out of answers"):
        fake.complete("S", "P3")


def test_fake_provider_default_answer_is_a_valid_draft():
    fake = FakeProvider()
    draft = parse_draft(fake.complete("S", "hello"))
    assert draft.summary == default_answer("S", "hello")["summary"]


# --- reading the model's answer ------------------------------------------------


def test_parse_draft_accepts_code_fence_and_surrounding_text():
    assert parse_draft('```json\n{"summary": "A"}\n```').summary == "A"
    assert parse_draft('Here you go:\n{"summary": "B"}\nThanks!').summary == "B"


def test_parse_draft_fixes_shapes_and_drops_empty_items():
    draft = parse_draft(json.dumps({
        "title": "  ",
        "summary": " S ",
        "decisions": ["Use SQLite", {"decision": "", "reason": "x"}, {"decision": "Ship v1", "reason": ""}],
        "open_questions": ["Q1", "", "Q1", None, "Q2"],
        "next_steps": "Only one step",
        "key_facts": [3, "fact"],
        "code_snippets": [{"code": "", "language": "py"}, {"code": "print(1)", "language": "", "path": "a.py"}],
        "file_refs": ["README.md", {"path": "", "description": "no path"}],
        "unknown_field": "ignored",
    }))
    assert draft.title is None
    assert draft.summary == "S"
    assert [(d.decision, d.reason) for d in draft.decisions] == [("Use SQLite", None), ("Ship v1", None)]
    assert draft.open_questions == ["Q1", "Q2"]
    assert draft.next_steps == ["Only one step"]
    assert draft.key_facts == ["3", "fact"]
    assert [(c.code, c.language, c.path) for c in draft.code_snippets] == [("print(1)", None, "a.py")]
    assert [f.path for f in draft.file_refs] == ["README.md"]


@pytest.mark.parametrize(("text", "message"), [
    ("no json here", "not JSON"),
    ("{broken", "not JSON"),
    ("{ 'single': quotes }", "not valid JSON"),
    ("[1, 2]", "not a JSON object"),
    ('{"summary": ""}', "summary is empty"),
    ('{"title": "only a title"}', "summary is empty"),
])
def test_parse_draft_rejects_unusable_answers(text, message):
    with pytest.raises(ValueError, match=message):
        parse_draft(text)


def test_schema_is_strict_everywhere():
    def check(node):
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert sorted(node["required"]) == sorted(node["properties"])
            for child in node["properties"].values():
                check(child)
        if node.get("type") == "array":
            check(node["items"])

    check(DRAFT_SCHEMA)
    assert set(DRAFT_SCHEMA["properties"]) == {
        "title", "summary", "decisions", "open_questions", "next_steps", "key_facts", "code_snippets", "file_refs",
    }


# --- short chats: one request --------------------------------------------------


def test_short_chat_is_one_request_and_fills_the_pack():
    fake = FakeProvider([DRAFT])
    pack = build_pack(conversation(SHORT_CHAT), fake)

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call.system == SYSTEM_PROMPT
    assert call.schema == DRAFT_SCHEMA
    assert "[1] USER (2026-03-01 09:00 UTC):\nShould we use SQLite" in call.prompt
    assert "[2] ASSISTANT:\nSQLite: one file" in call.prompt

    assert isinstance(pack, ContextPack)
    assert pack.title == "Database choice"
    assert pack.summary == DRAFT["summary"]
    assert pack.decisions[0].decision == "Use SQLite"
    assert pack.decisions[0].reason == "One file, no server."
    assert pack.open_questions == ["Where should the database file live?"]
    assert pack.file_refs[0].path == "contextos/store.py"
    assert pack.source.tool == "chatgpt"
    assert pack.source.conversation_id == "conv-1"
    assert pack.source.title == "Pick a database"
    assert pack.source.url == "https://chatgpt.com/c/conv-1"
    assert pack.source.created_at == T0
    assert pack.raw_transcript is None
    ContextPack.from_json(pack.to_json())  # round trip stays valid


def test_title_falls_back_to_conversation_then_placeholder():
    no_title = {**DRAFT, "title": ""}
    assert build_pack(conversation(SHORT_CHAT), FakeProvider([no_title])).title == "Pick a database"
    untitled = build_pack(conversation(SHORT_CHAT, title=None), FakeProvider([no_title]))
    assert untitled.title == "Untitled conversation"


def test_transcript_is_included_only_when_asked():
    pack = build_pack(conversation(SHORT_CHAT), FakeProvider([DRAFT]), include_transcript=True)
    assert [m.content for m in pack.raw_transcript] == [m.content for m in SHORT_CHAT]


def test_bad_json_is_retried_once():
    fake = FakeProvider(["Sorry, here is a summary in prose.", DRAFT])
    pack = build_pack(conversation(SHORT_CHAT), fake)
    assert pack.title == "Database choice"
    assert len(fake.calls) == 2
    assert "could not be used (the answer is not JSON)" in fake.calls[1].prompt


def test_gives_up_after_two_bad_answers():
    fake = FakeProvider(["nope", '{"summary": ""}'])
    with pytest.raises(PackBuildError, match="after 2 tries: the summary is empty"):
        build_pack(conversation(SHORT_CHAT), fake)


def test_provider_errors_are_not_hidden():
    def broken(system, prompt):
        raise ProviderError("Could not reach Ollama")

    with pytest.raises(ProviderError, match="Could not reach Ollama"):
        build_pack(conversation(SHORT_CHAT), FakeProvider(broken))


def test_empty_conversation_is_an_error():
    blank = [Message(role="user", content="   ")]
    with pytest.raises(PackBuildError, match="no messages"):
        build_pack(conversation([]), FakeProvider())
    with pytest.raises(PackBuildError, match="no messages"):
        build_pack(conversation(blank), FakeProvider())


# --- long chats: parts, then a merge -------------------------------------------


def test_split_parts_keeps_order_and_size():
    messages = numbered_chat(30)
    parts = split_parts(messages, 1_000)
    assert len(parts) > 1
    assert all(len(p) <= 1_000 for p in parts)
    joined = "\n\n".join(parts)
    positions = [joined.index(f"message-{i:03d}") for i in range(30)]
    assert positions == sorted(positions)


def test_split_parts_cuts_one_huge_message():
    huge = Message(role="user", content="A" * 3_500)
    parts = split_parts([huge], 1_000)
    assert len(parts) == 4
    assert all(len(p) <= 1_000 for p in parts)
    assert parts[1].startswith("[1] (continued)\n")
    assert sum(p.count("A") for p in parts) == 3_500


def test_long_chat_is_summarized_in_parts_then_merged():
    progress = []

    def answer(system, prompt):
        if prompt.startswith("This is part"):
            first = prompt.split("message-", 1)[1][:3]
            return {"summary": f"notes from message {first}", "next_steps": [f"step {first}"]}
        return {**DRAFT, "title": "Merged"}

    fake = FakeProvider(answer)
    pack = build_pack(conversation(numbered_chat(30)), fake, max_chars=1_500, progress=progress.append)

    part_calls = [c for c in fake.calls if c.prompt.startswith("This is part")]
    combine_calls = [c for c in fake.calls if c.prompt.startswith("Below are notes")]
    count = len(part_calls)
    assert count > 2
    assert [c.prompt.split(" of ")[0] for c in part_calls] == [f"This is part {i}" for i in range(1, count + 1)]
    assert all(f"of {count} of one long conversation" in c.prompt for c in part_calls)
    # Every message reaches the model exactly once, in order.
    text = "".join(c.prompt for c in part_calls)
    assert [text.count(f"message-{i:03d}") for i in range(30)] == [1] * 30

    assert len(combine_calls) == 1
    merged_prompt = combine_calls[0].prompt
    assert f"notes on {count} consecutive parts" in merged_prompt
    assert merged_prompt.index("notes from message 000") < merged_prompt.index("step 0")  # notes kept in order
    assert pack.title == "Merged"
    assert progress[0] == f"Summarizing part 1 of {count}"
    assert progress[-1] == "Combining the part summaries"


def test_many_parts_are_merged_in_rounds():
    def answer(system, prompt):
        filler = "n" * 400  # large notes force several merge rounds
        return {"summary": f"notes {len(prompt)} {filler}"}

    fake = FakeProvider(answer)
    pack = build_pack(conversation(numbered_chat(60)), fake, max_chars=1_200)

    parts = sum(c.prompt.startswith("This is part") for c in fake.calls)
    combines = sum(c.prompt.startswith("Below are notes") for c in fake.calls)
    assert parts >= 8
    assert 2 <= combines < parts  # more than one merge, and each round shrinks the list
    assert pack.summary.startswith("notes")


def test_part_size_comes_from_the_provider():
    fake = FakeProvider(max_input_chars=6_000)
    build_pack(conversation(numbered_chat(60)), fake)
    assert sum(c.prompt.startswith("This is part") for c in fake.calls) > 1

    roomy = FakeProvider()
    build_pack(conversation(numbered_chat(60)), roomy)
    assert len(roomy.calls) == 1

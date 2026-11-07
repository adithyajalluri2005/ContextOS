"""Ollama's cloud service. No test calls it: requests go to a recording fake.
The key below is made up."""

import io
import json
import urllib.error

import pytest

from contextos.llm import ProviderError, get_provider
from contextos.llm.ollama_provider import CLOUD_HOST, DEFAULT_CLOUD_MODEL, DEFAULT_MODEL, OllamaProvider

KEY = "test-key-" + "0123456789abcdef"
OK = {"message": {"content": '{"summary": "ok"}'}, "done_reason": "stop"}


class FakeHTTPResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def recording_urlopen(answer=OK):
    seen = []

    def urlopen(request, timeout):
        seen.append(request)
        if isinstance(answer, Exception):
            raise answer
        return FakeHTTPResponse(json.dumps(answer).encode())

    return urlopen, seen


def http_error(code: int, body: bytes = b'{"error": "nope"}'):
    return urllib.error.HTTPError("u", code, "Error", {}, io.BytesIO(body))


def test_conftest_removes_the_real_key(monkeypatch):
    import os

    assert "OLLAMA_API_KEY" not in os.environ
    assert "OLLAMA_HOST" not in os.environ


def test_key_switches_to_cloud_and_sends_bearer_token():
    urlopen, seen = recording_urlopen()
    provider = OllamaProvider(api_key=KEY, urlopen=urlopen)
    assert provider.cloud
    assert provider.host == CLOUD_HOST
    assert provider.model == DEFAULT_CLOUD_MODEL
    assert provider.complete("S", "P") == '{"summary": "ok"}'

    request = seen[0]
    assert request.full_url == "https://ollama.com/api/chat"
    assert request.get_header("Authorization") == f"Bearer {KEY}"
    assert json.loads(request.data)["model"] == DEFAULT_CLOUD_MODEL


def test_key_comes_from_environment(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", f"  {KEY}  ")
    urlopen, seen = recording_urlopen()
    OllamaProvider(urlopen=urlopen).complete("S", "P")
    assert seen[0].get_header("Authorization") == f"Bearer {KEY}"


def test_without_key_stays_local_and_sends_no_token():
    urlopen, seen = recording_urlopen()
    provider = OllamaProvider(urlopen=urlopen)
    assert not provider.cloud
    assert provider.model == DEFAULT_MODEL
    provider.complete("S", "P")
    assert seen[0].full_url == "http://localhost:11434/api/chat"
    assert seen[0].get_header("Authorization") is None


def test_blank_key_counts_as_no_key(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "   ")
    assert not OllamaProvider().cloud


def test_chosen_model_wins_on_cloud(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", KEY)
    provider = get_provider(env={"CONTEXTOS_PROVIDER": "ollama", "CONTEXTOS_MODEL": "qwen3-coder:480b"})
    assert provider.cloud
    assert provider.model == "qwen3-coder:480b"


def test_key_with_own_https_host():
    urlopen, seen = recording_urlopen()
    OllamaProvider(api_key=KEY, host="https://ollama.internal.example.com", urlopen=urlopen).complete("S", "P")
    assert seen[0].full_url == "https://ollama.internal.example.com/api/chat"
    assert seen[0].get_header("Authorization") == f"Bearer {KEY}"


@pytest.mark.parametrize("host", ["localhost", "http://127.0.0.1:11434", "[::1]:11434"])
def test_key_may_go_to_local_ollama_over_http(host):
    urlopen, seen = recording_urlopen()
    OllamaProvider(api_key=KEY, host=host, urlopen=urlopen).complete("S", "P")
    assert seen[0].full_url.startswith("http://")


@pytest.mark.parametrize("host", ["gpu-box", "http://ollama.example.com", "http://10.0.0.5:11434"])
def test_key_is_never_sent_over_plain_http_to_another_computer(host):
    with pytest.raises(ProviderError, match="Not sending OLLAMA_API_KEY over plain http") as caught:
        OllamaProvider(api_key=KEY, host=host)
    assert KEY not in str(caught.value)


@pytest.mark.parametrize("code", [401, 403])
def test_rejected_key_message(code):
    urlopen, _ = recording_urlopen(http_error(code))
    with pytest.raises(ProviderError, match="rejected the API key") as caught:
        OllamaProvider(api_key=KEY, urlopen=urlopen).complete("S", "P")
    assert KEY not in str(caught.value)


def test_missing_key_message():
    urlopen, _ = recording_urlopen(http_error(401))
    with pytest.raises(ProviderError, match="needs an API key. Set OLLAMA_API_KEY"):
        OllamaProvider(host="https://ollama.com", urlopen=urlopen).complete("S", "P")


def test_unknown_cloud_model_message():
    urlopen, _ = recording_urlopen(http_error(404))
    with pytest.raises(ProviderError, match="cloud service does not offer the model 'nope'") as caught:
        OllamaProvider("nope", api_key=KEY, urlopen=urlopen).complete("S", "P")
    assert "ollama pull" not in str(caught.value)


def test_unreachable_cloud_message():
    urlopen, _ = recording_urlopen(urllib.error.URLError("no network"))
    with pytest.raises(ProviderError, match="Could not reach Ollama's cloud service"):
        OllamaProvider(api_key=KEY, urlopen=urlopen).complete("S", "P")


def test_key_is_not_shown_in_repr():
    provider = OllamaProvider(api_key=KEY)
    assert KEY not in repr(provider)
    assert "key=set" in repr(provider)

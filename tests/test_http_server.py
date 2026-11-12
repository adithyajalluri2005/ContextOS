"""Tests for `contextos serve`: the MCP server over HTTP behind a secret link.

No network and no real AI service: requests go straight into the web app in memory.
"""

import json

import pytest

pytest.importorskip("mcp")

from starlette.testclient import TestClient  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from contextos import mcp_server  # noqa: E402
from contextos.cli import app as cli_app  # noqa: E402
from contextos.store import Store  # noqa: E402

SECRET = "TestSecret_0123456789abcdefghijklmnopqrstuvwxyz"
PUBLIC_HOST = "example-tunnel.ngrok-free.dev"
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def _rpc(method, params=None, id=1):
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}}


def _init():
    return _rpc(
        "initialize",
        {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
    )


@pytest.fixture
def client():
    app = mcp_server.build_http_app(SECRET, PUBLIC_HOST)
    with TestClient(app, base_url=f"https://{PUBLIC_HOST}") as c:
        yield c


def _call_tool(client, name, arguments):
    response = client.post(f"/{SECRET}/mcp", headers=HEADERS, json=_rpc("tools/call", {"name": name, "arguments": arguments}))
    assert response.status_code == 200, response.text
    return response.json()["result"]


# --- the secret link -------------------------------------------------------------------


def test_right_link_answers(client):
    response = client.post(f"/{SECRET}/mcp", headers=HEADERS, json=_init())
    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"]


@pytest.mark.parametrize(
    "path",
    ["/mcp", "/", f"/{SECRET[:-1]}/mcp", f"/{SECRET}x/mcp", "/wrong-secret-0123456789abcdefghijklmnop/mcp", f"/{SECRET}"],
)
def test_any_other_path_is_not_found(client, path):
    response = client.post(path, headers=HEADERS, json=_init())
    assert response.status_code == 404
    assert SECRET not in response.text


def test_unknown_host_is_refused():
    app = mcp_server.build_http_app(SECRET, PUBLIC_HOST)
    with TestClient(app, base_url="https://attacker.example") as c:
        response = c.post(f"/{SECRET}/mcp", headers=HEADERS, json=_init())
    assert response.status_code in (400, 403, 421)


def test_without_public_host_only_this_computer_works():
    with TestClient(mcp_server.build_http_app(SECRET), base_url="http://127.0.0.1:8765") as c:
        assert c.post(f"/{SECRET}/mcp", headers=HEADERS, json=_init()).status_code == 200
    with TestClient(mcp_server.build_http_app(SECRET), base_url=f"https://{PUBLIC_HOST}") as c:
        assert c.post(f"/{SECRET}/mcp", headers=HEADERS, json=_init()).status_code != 200


def test_short_secret_is_refused():
    with pytest.raises(ValueError):
        mcp_server.build_http_app("short")


# --- the tools work over HTTP ------------------------------------------------------------


def test_tools_save_and_load_over_http(client):
    listed = client.post(f"/{SECRET}/mcp", headers=HEADERS, json=_rpc("tools/list")).json()
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert names == {"save_context", "list_contexts", "search_contexts", "load_context"}

    saved = _call_tool(
        client,
        "save_context",
        {"title": "Made-up web test", "summary": "Saved over HTTP. Key sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789AbCdEfGh"},
    )
    assert not saved.get("isError")
    loaded = _call_tool(client, "load_context", {})
    text = loaded["content"][0]["text"]
    assert "Made-up web test" in text
    assert "sk-proj-" not in text  # secrets are still hidden before saving
    assert Store().recent(limit=1)[0].title == "Made-up web test"


# --- the secret itself ---------------------------------------------------------------------


def test_secret_is_made_once_and_kept(monkeypatch):
    monkeypatch.delenv(mcp_server.SECRET_ENV, raising=False)
    first = mcp_server.load_secret()
    assert len(first) >= mcp_server.MIN_SECRET_CHARS
    assert mcp_server.secret_path().exists()
    assert mcp_server.load_secret() == first


def test_new_secret_replaces_old(monkeypatch):
    monkeypatch.delenv(mcp_server.SECRET_ENV, raising=False)
    first = mcp_server.load_secret()
    second = mcp_server.load_secret(renew=True)
    assert second != first
    assert mcp_server.load_secret() == second


def test_secret_from_environment_wins(monkeypatch):
    monkeypatch.setenv(mcp_server.SECRET_ENV, SECRET)
    assert mcp_server.load_secret() == SECRET
    assert not mcp_server.secret_path().exists()


def test_bad_secret_in_file_is_refused(monkeypatch):
    monkeypatch.delenv(mcp_server.SECRET_ENV, raising=False)
    path = mcp_server.secret_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("too-short\n", encoding="utf-8")
    with pytest.raises(ValueError, match="--new-secret"):
        mcp_server.load_secret()


# --- the command ------------------------------------------------------------------------------


def test_serve_command_prints_link_and_turns_off_access_log(monkeypatch):
    monkeypatch.setenv(mcp_server.SECRET_ENV, SECRET)
    seen = {}

    def fake_uvicorn_run(app, **kwargs):
        seen.update(kwargs)

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_uvicorn_run)
    result = CliRunner().invoke(cli_app, ["serve", "--public-host", f"https://{PUBLIC_HOST}/", "--port", "9000"])
    assert result.exit_code == 0, result.output
    assert f"https://{PUBLIC_HOST}/{SECRET}/mcp" in result.output
    assert f"http://127.0.0.1:9000/{SECRET}/mcp" in result.output
    assert seen["host"] == "127.0.0.1"
    assert seen["port"] == 9000
    assert seen["access_log"] is False


def test_serve_command_explains_bad_secret(monkeypatch):
    monkeypatch.setenv(mcp_server.SECRET_ENV, "short")
    result = CliRunner().invoke(cli_app, ["serve"])
    assert result.exit_code == 1
    assert "--new-secret" in result.output


def test_load_context_json_over_http(client):
    _call_tool(client, "save_context", {"title": "JSON check", "summary": "made-up"})
    loaded = _call_tool(client, "load_context", {"format": "json"})
    assert json.loads(loaded["content"][0]["text"])["title"] == "JSON check"

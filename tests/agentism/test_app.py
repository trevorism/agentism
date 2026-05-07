import pytest

from agentism import app


@pytest.mark.asyncio
async def test_load_github_mcp_tools_uses_direct_client(monkeypatch):
    created = {}

    class FakeClient:
        def __init__(self, config_map):
            created["config_map"] = config_map

        async def get_tools(self):
            return ["gh-tool"]

    monkeypatch.setattr(app, "MultiServerMCPClient", FakeClient)
    monkeypatch.setattr(app.config, "GITHUB_TOKEN", "token-123")

    tools, client = await app._load_github_mcp_tools()

    assert tools == ["gh-tool"]
    assert isinstance(client, FakeClient)
    assert created["config_map"]["github"]["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"] == "token-123"


@pytest.mark.asyncio
async def test_safe_close_async_prefers_aclose():
    events = []

    class Resource:
        async def aclose(self):
            events.append("aclose")

        def close(self):
            events.append("close")

    await app._safe_close_async(Resource())

    assert events == ["aclose"]


@pytest.mark.asyncio
async def test_safe_close_async_handles_sync_close():
    events = []

    class Resource:
        def close(self):
            events.append("close")

    await app._safe_close_async(Resource())

    assert events == ["close"]


def test_ollama_client_kwargs_includes_temperature_and_top_p(monkeypatch):
    monkeypatch.setattr(app.config, "OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setattr(app.config, "OLLAMA_TEMPERATURE", 0.7)
    monkeypatch.setattr(app.config, "OLLAMA_TOP_P", 0.95)

    kwargs = app._ollama_client_kwargs("qwen3.6")

    assert kwargs["model"] == "qwen3.6"
    assert kwargs["temperature"] == 0.7
    assert kwargs["top_p"] == 0.95
    assert "model_kwargs" not in kwargs


def test_ollama_client_kwargs_can_omit_top_p(monkeypatch):
    monkeypatch.setattr(app.config, "OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setattr(app.config, "OLLAMA_TEMPERATURE", 0.7)
    monkeypatch.setattr(app.config, "OLLAMA_TOP_P", None)

    kwargs = app._ollama_client_kwargs("llama3.2")

    assert kwargs["model"] == "llama3.2"
    assert kwargs["temperature"] == 0.7
    assert "top_p" not in kwargs
    assert "model_kwargs" not in kwargs



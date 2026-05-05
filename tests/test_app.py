import pytest

import app


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


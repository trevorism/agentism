import pytest

from agentism import streaming


class _Bound:
    def __init__(self, response=None, should_raise=False):
        self._response = response
        self._should_raise = should_raise

    async def ainvoke(self, _messages):
        if self._should_raise:
            raise RuntimeError("probe failure")
        return self._response


class _Resp:
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls


@pytest.mark.asyncio
async def test_probe_tool_calling_uses_aclose(monkeypatch):
    class _LLM:
        def __init__(self):
            self.closed = False

        def bind_tools(self, _tools):
            return _Bound(_Resp([{"name": "_ping"}]))

        async def aclose(self):
            self.closed = True

    llm = _LLM()
    monkeypatch.setattr(streaming, "ChatOllama", lambda **kwargs: llm)

    ok = await streaming.probe_tool_calling("test-model")

    assert ok is True
    assert llm.closed is True


@pytest.mark.asyncio
async def test_probe_tool_calling_falls_back_to_close(monkeypatch):
    class _LLM:
        def __init__(self):
            self.closed = False

        def bind_tools(self, _tools):
            return _Bound(_Resp([]))

        def close(self):
            self.closed = True

    llm = _LLM()
    monkeypatch.setattr(streaming, "ChatOllama", lambda **kwargs: llm)

    ok = await streaming.probe_tool_calling("test-model")

    assert ok is False
    assert llm.closed is True


@pytest.mark.asyncio
async def test_probe_tool_calling_ignores_missing_close(monkeypatch):
    class _LLM:
        def bind_tools(self, _tools):
            return _Bound(_Resp([]), should_raise=True)

    monkeypatch.setattr(streaming, "ChatOllama", lambda **kwargs: _LLM())

    ok = await streaming.probe_tool_calling("test-model")

    assert ok is False



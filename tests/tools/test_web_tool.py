from tools import web_tool


class _FakeResponse:
    def __init__(self, text: str = "ok", status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        return None


class _FakeClient:
    def __init__(self, recorder: dict):
        self.recorder = recorder

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, json=None, headers=None):
        self.recorder["url"] = url
        self.recorder["json"] = json
        self.recorder["headers"] = headers
        return _FakeResponse("created")


class _FakeSpecClient:
    def __init__(self, responses: dict[str, _FakeResponse], calls: list[str]):
        self.responses = responses
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url, headers=None):
        self.calls.append(url)
        return self.responses.get(url, _FakeResponse("", 404))


def test_post_platform_api_sets_bearer_header_and_uses_json_payload(monkeypatch):
    calls = {}

    monkeypatch.setattr(web_tool, "_get_token", lambda force_refresh=False: "abc123")
    monkeypatch.setattr(
        web_tool.httpx,
        "Client",
        lambda *args, **kwargs: _FakeClient(calls),
    )

    result = web_tool.post_platform_api.func(
        "/policy",
        '{"name":"critical-policy","description":"a policy rule","operator":">=","value":4}',
    )

    assert result == "created"
    assert calls["headers"]["Authorization"] == "Bearer abc123"
    assert calls["json"]["name"] == "critical-policy"
    assert calls["json"]["operator"] == ">="
    assert calls["json"]["value"] == 4


def test_post_platform_api_accepts_dict_json_body(monkeypatch):
    calls = {}

    monkeypatch.setattr(web_tool, "_get_token", lambda force_refresh=False: "abc123")
    monkeypatch.setattr(
        web_tool.httpx,
        "Client",
        lambda *args, **kwargs: _FakeClient(calls),
    )

    result = web_tool.post_platform_api.func(
        "/policy",
        {"name": "critical-policy", "description": "critical lower bound", "operator": "<=", "value": 2},
    )

    assert result == "created"
    assert calls["headers"]["Authorization"] == "Bearer abc123"
    assert calls["json"]["name"] == "critical-policy"
    assert calls["json"]["value"] == 2


def test_post_platform_api_rejects_non_json_body_type():
    result = web_tool.post_platform_api.func("/policy", 123)

    assert "Invalid JSON body" in result


def test_get_platform_api_spec_discovers_spec_from_help_page(monkeypatch):
    base = "https://service.example.test"
    calls = []
    help_html = '<html><body><a href="/v3/api-docs">OpenAPI</a></body></html>'
    openapi_json = '{"openapi":"3.0.1","paths":{}}'

    responses = {
        f"{base}/help": _FakeResponse(help_html, 200),
        f"{base}/v3/api-docs": _FakeResponse(openapi_json, 200),
    }

    monkeypatch.setattr(web_tool, "_SPEC_CACHE", {})
    monkeypatch.setattr(web_tool, "_auth_headers", lambda: {})
    monkeypatch.setattr(
        web_tool.httpx,
        "Client",
        lambda *args, **kwargs: _FakeSpecClient(responses, calls),
    )

    result = web_tool.get_platform_api_spec.func(service_base_url=base, force_refresh=True)

    assert '"openapi":"3.0.1"' in result
    assert calls[0] == f"{base}/help"
    assert f"{base}/v3/api-docs" in calls


def test_get_platform_api_spec_tries_help_before_other_paths(monkeypatch):
    base = "https://service.example.test"
    calls = []
    responses = {
        f"{base}/help": _FakeResponse("<html></html>", 404),
        f"{base}/swagger/swagger.yml": _FakeResponse("", 404),
        f"{base}/swagger/swagger.json": _FakeResponse("", 404),
        f"{base}/swagger-ui/swagger.json": _FakeResponse("", 404),
        f"{base}/v3/api-docs/swagger-config": _FakeResponse("", 404),
        f"{base}/v3/api-docs": _FakeResponse("", 404),
        f"{base}/v2/api-docs": _FakeResponse("", 404),
        f"{base}/openapi.json": _FakeResponse("", 404),
        f"{base}/openapi.yaml": _FakeResponse("", 404),
    }

    monkeypatch.setattr(web_tool, "_SPEC_CACHE", {})
    monkeypatch.setattr(web_tool, "_auth_headers", lambda: {})
    monkeypatch.setattr(
        web_tool.httpx,
        "Client",
        lambda *args, **kwargs: _FakeSpecClient(responses, calls),
    )

    _ = web_tool.get_platform_api_spec.func(service_base_url=base, force_refresh=True)

    assert calls
    assert calls[0] == f"{base}/help"


def test_get_platform_api_spec_discovers_versioned_swagger_yaml_from_help(monkeypatch):
    base = "https://service.example.test"
    calls = []
    help_html = '<html><body><a href="/swagger/service-api-1.0.yml">Swagger YAML</a></body></html>'
    swagger_yaml = "openapi: 3.0.1\npaths: {}\n"

    responses = {
        f"{base}/help": _FakeResponse(help_html, 200),
        f"{base}/swagger/service-api-1.0.yml": _FakeResponse(swagger_yaml, 200),
    }

    monkeypatch.setattr(web_tool, "_SPEC_CACHE", {})
    monkeypatch.setattr(web_tool, "_auth_headers", lambda: {})
    monkeypatch.setattr(
        web_tool.httpx,
        "Client",
        lambda *args, **kwargs: _FakeSpecClient(responses, calls),
    )

    result = web_tool.get_platform_api_spec.func(service_base_url=base, force_refresh=True)

    assert "openapi: 3.0.1" in result
    assert calls[0] == f"{base}/help"
    assert f"{base}/swagger/service-api-1.0.yml" in calls



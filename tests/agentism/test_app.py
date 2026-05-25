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


def test_routing_models_uses_env_overrides(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL_EXECUTOR", "exec-model")
    monkeypatch.setenv("OLLAMA_MODEL_PLANNER", "plan-model")
    monkeypatch.setenv("OLLAMA_MODEL_CRITIC", "critic-model")

    models = app._routing_models("base-model")

    assert models["executor"] == "exec-model"
    assert models["planner"] == "plan-model"
    assert models["critic"] == "critic-model"


def test_select_turn_model_prefers_planner_for_review_prompts():
    models = {
        "default": "base",
        "executor": "exec",
        "planner": "plan",
        "critic": "crit",
    }

    selected = app._select_turn_model("Please review this PR and summarize risks", "base", models)

    assert selected == "plan"


def test_select_turn_model_prefers_executor_for_implementation_prompts():
    models = {
        "default": "base",
        "executor": "exec",
        "planner": "plan",
        "critic": "crit",
    }

    selected = app._select_turn_model("Implement a fix for this bug", "base", models)

    assert selected == "exec"


def test_should_run_critic_pass_for_implementation_without_verification_text():
    should_run = app._should_run_critic_pass(
        "Implement a fix for issue #7",
        "I changed the code in src/main.py and it should work now.",
    )

    assert should_run is True


def test_should_not_run_critic_pass_when_verification_is_present():
    should_run = app._should_run_critic_pass(
        "Implement a fix for issue #7",
        "Updated src/main.py and ran pytest with all tests passed.",
    )

    assert should_run is False


def test_looks_like_auto_mode_interim_response_for_execution_plan():
    response = """I will upgrade the repositories to the latest compatible versions.\n\nExecution Plan\n1. Baseline Assessment\n2. Apply upgrades\n3. Validate results"""

    should_continue = app._looks_like_auto_mode_interim_response(
        "Upgrade the repositories and verify the results",
        response,
    )

    assert should_continue is True


def test_looks_like_auto_mode_interim_response_for_confirmation_request():
    should_continue = app._looks_like_auto_mode_interim_response(
        "Implement the bug fix",
        "I inspected the code and have a plan. Please confirm and I will proceed.",
    )

    assert should_continue is True


def test_looks_like_auto_mode_interim_response_ignores_completed_result():
    should_continue = app._looks_like_auto_mode_interim_response(
        "Implement the bug fix",
        "Updated src/main.py, ran pytest, and all tests passed.",
    )

    assert should_continue is False


def test_looks_like_auto_mode_interim_response_ignores_real_blocker():
    should_continue = app._looks_like_auto_mode_interim_response(
        "Implement the bug fix",
        "I cannot proceed because the repository was not found with the provided owner/repo.",
    )

    assert should_continue is False


def test_build_auto_mode_continue_prompt_demands_completed_result():
    prompt = app._build_auto_mode_continue_prompt("Implement the bug fix")

    assert "Do not ask for confirmation" in prompt
    assert "Only respond when you have a concrete result" in prompt
    assert "Original request:\nImplement the bug fix" in prompt


def test_augment_user_input_with_memory_includes_context_and_request():
    result = app._augment_user_input_with_memory(
        "Implement the fix",
        "- [summary] We already reproduced the issue",
    )

    assert "Thread memory context" in result
    assert "Current user request" in result
    assert "Implement the fix" in result


def test_augment_user_input_with_memory_returns_original_when_empty():
    result = app._augment_user_input_with_memory("Implement the fix", "")

    assert result == "Implement the fix"



# AGENTS.md

## What this project is
- `agentism` is a local coding agent: LangGraph ReAct orchestration + Ollama LLM + local tools + GitHub MCP tools.
- Main runtime path is `agent.py` -> `agentism/__main__.py` -> `agentism/app.py::main_async`.

## Architecture you need to understand first
- Tool stack is composed at runtime in `agentism/app.py`: `LOCAL_TOOLS` (from `tools/__init__.py`) + GitHub MCP tools loaded through `MultiServerMCPClient`.
- System prompt is generated dynamically in `agentism/prompts.py::build_system_prompt`, including:
  - base policy text,
  - injected `agentism/knowledge/*.md` content,
  - live tool metadata + required parameter hints from `agentism/tool_metadata.py`.
- Turn execution streams chunks in `agentism/streaming.py::run_agent_turn`; it prints tool-call previews/results and tracks token usage from `usage_metadata`.
- REPL commands (`!help`, `!model`, `!clear`, `!issue`, `!review`, `!health`, etc.) are declarative in `agentism/commands.py` via `_COMMANDS` + `dispatch` signature introspection.

## Environment and dependency realities
- Required env vars are enforced in `agentism/config.py` (`_required` exits process): at minimum `OLLAMA_MODEL`, `GITHUB_TOKEN`, `PS_MODULE_PATH`.
- External runtime dependencies are not optional for full behavior:
  - Ollama server (`OLLAMA_BASE_URL`) for model inference,
  - Node.js + `npx @modelcontextprotocol/server-github` for GitHub tools,
  - PowerShell 7 (`pwsh`) for shell/platform tools (`tools/shell.py`).
- Repositories are resolved through `tools/repo_paths.py`: absolute path -> recursive lookup under `DEV_DIR` -> fallback `WORKSPACE_DIR`.

## Developer workflows (actual commands)
- Install deps: `uv sync`
- Run agent: `uv run python agent.py` (or `uv run agentism`)
- Unit/CI-safe tests: `uv run pytest`
- Integration-only tests: `uv run pytest -o addopts='' -m integration`
- Useful debug path in REPL: `!health` for environment diagnostics (`tools/health.py`).

## Project-specific coding/testing patterns
- Test isolation is intentional: `tests/conftest.py` rewires `HOME`, `DEV_DIR`, `WORKSPACE_DIR`, and `MEMORY_DB` into `.test_sandbox` before app imports.
- Default pytest config in `pyproject.toml` excludes integration tests (`-m 'not integration'`).
- Discovery/search tools share a strict allow/deny file policy in `tools/discovery_filters.py`; avoid bypassing it in new repo-scanning features.
- `master` is treated as protected in local git tools (`tools/git_tool.py::PROTECTED_BRANCHES`); workflow expects feature branch -> commit/push -> PR.
- `tools/test_runner.py` auto-detects suites by repo layout (Gradle, Cucumber `.feature`, Vitest) and is the intended cross-language test entrypoint.

## Integration points and communication patterns
- GitHub operations are expected through MCP tool contracts (parameter names matter; see `agentism/tool_metadata.py` hints).
- Platform API/CLI behavior is encoded in `agentism/knowledge/*.md` (not hardcoded in tool modules); keep those docs in sync with runtime expectations.
- `agentism/cli.py::startup_plan` injects high-autonomy prompts for `--issue` / `--issues`; changing that text changes agent behavior significantly.

## When editing this codebase
- If you add a tool, register it in `tools/__init__.py` (`LOCAL_TOOLS`) or it will never be available to the agent.
- If you touch streaming/turn execution, validate both normal tool flow and dangling-tool-call recovery in `agentism/app.py` (`clear_thread` retry path).


# Agentism – Local Platform Dev Agent

A local agent (LangGraph + Ollama) that can develop software

**GitHub tools** are loaded dynamically at startup via the GitHub MCP server (Node.js process, stdio transport). They include: search code, list/create issues, read/write files, list/create PRs, and more.

## Prerequisites

| Requirement | Notes |
|---|---|
| [Ollama](https://ollama.com) running locally | `ollama pull llama3.2` |
| [Node.js](https://nodejs.org) ≥ 18 | needed for `npx @modelcontextprotocol/server-github` |
| Python ≥ 3.12 + [uv](https://docs.astral.sh/uv/) | already configured |
| GitHub Personal Access Token | scopes: `repo`, `read:org`, `workflow` |

## Setup

```powershell
# 1. Copy env template
cp .env.example .env

# 2. Fill in .env (GITHUB_TOKEN, PLATFORM_BASE_URL, etc.)
notepad .env

# 3. Install dependencies
uv sync

# 4. Run
uv run python agent.py
```

## Testing

By default, pytest skips integration tests (the ones that require local services,
credentials, or machine-specific setup). This keeps CI independent from `.env`.

```powershell
# Default (unit/CI-safe tests)
uv run pytest

# Integration tests only (requires local setup + valid .env)
uv run pytest -o addopts='' -m integration
```

## Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_MODEL` | `llama3.2` | Any Ollama model that supports tool-calling |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server address |
| `GITHUB_TOKEN` | *(required)* | PAT for GitHub API + MCP |
| `GITHUB_DEFAULT_OWNER` | *(optional)* | Default org/user for GitHub operations |
| `PLATFORM_BASE_URL` | `http://localhost:8080` | Your Groovy backend base URL |
| `MEMORY_DB` | `memory.db` | SQLite file for persistent conversation memory |
| `WORKSPACE_DIR` | `./repos` | Where repos are cloned to |

## Extending

- Add a new tool: create a `@tool` function in `tools/` and add it to `LOCAL_TOOLS` in `tools/__init__.py`.
- Switch models: change `OLLAMA_MODEL` in `.env` (try `qwen2.5-coder:14b` for better code generation).
- Multi-thread conversations: change `thread_id` handling in `app.py` to support parallel sessions.

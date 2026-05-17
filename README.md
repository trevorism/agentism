# Agentism
![Build](https://github.com/trevorism/agentism/actions/workflows/build.yml/badge.svg)
![GitHub last commit](https://img.shields.io/github/last-commit/trevorism/agentism)
![GitHub language count](https://img.shields.io/github/languages/count/trevorism/agentism)
![GitHub top language](https://img.shields.io/github/languages/top/trevorism/agentism)

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
| `OLLAMA_TEMPERATURE` | `0.7` | Sampling temperature (higher default for more exploratory reasoning) |
| `OLLAMA_TOP_P` | `0.95` | Nucleus sampling cutoff |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Embedding model used for semantic memory retrieval |
| `GITHUB_TOKEN` | *(required)* | PAT for GitHub API + MCP |
| `GITHUB_DEFAULT_OWNER` | *(optional)* | Default org/user for GitHub operations |
| `PLATFORM_BASE_URL` | `http://localhost:8080` | Your Groovy backend base URL |
| `MEMORY_DB` | `memory.db` | SQLite file for persistent conversation memory |
| `MEMORY_RETRIEVAL_LIMIT` | `8` | Max memory snippets retrieved per turn |
| `MEMORY_CONTEXT_CHAR_BUDGET` | `2400` | Max characters injected from memory per turn |
| `MEMORY_CHUNK_CHARS` | `600` | Chunk size for embedded memory content |
| `MEMORY_CHUNK_OVERLAP` | `120` | Overlap between adjacent memory chunks |
| `WORKSPACE_DIR` | `./repos` | Where repos are cloned to |

## Semantic memory (thread-scoped)

- Conversation turns are written to SQLite memory tables and embedded with `OLLAMA_EMBED_MODEL`.
- Retrieval is strict to the active `thread_id`; cross-thread recall is intentionally disabled.
- `!clear` removes both checkpoint rows and semantic memory for the current thread.
- If sqlite-vec is unavailable at runtime, retrieval falls back to in-process cosine scoring over stored embeddings.

Quick demo:

```powershell
uv run python -m agentism.memory_demo --thread demo --query "What changed for login?"
```

## Extending

- Add a new tool: create a `@tool` function in `tools/` and add it to `LOCAL_TOOLS` in `tools/__init__.py`.
- Switch models: change `OLLAMA_MODEL` in `.env` (try `qwen2.5-coder:14b` for better code generation).
- Multi-thread conversations: change `thread_id` handling in `app.py` to support parallel sessions.

import pytest

from agentism.memory_store import SqliteVecMemoryStore


async def _embed(text: str) -> list[float]:
    text = (text or "").lower()
    return [
        1.0 if "login" in text else 0.0,
        1.0 if "bug" in text else 0.0,
        1.0 if "recipe" in text else 0.0,
        float(len(text) % 11) / 10.0,
    ]


@pytest.mark.asyncio
async def test_retrieve_context_is_thread_scoped(tmp_path):
    db_path = tmp_path / "memory.db"
    store = SqliteVecMemoryStore(
        str(db_path),
        embed_model="nomic-embed-text",
        embed_fn=_embed,
        prefer_vec=False,
        chunk_chars=120,
        chunk_overlap=20,
    )

    await store.initialize()
    await store.add_turn("thread-a", "Please fix login bug", "I fixed the login handler bug")
    await store.add_turn("thread-b", "Need a pasta recipe", "Use olive oil and garlic")

    snippets = await store.retrieve_context(
        "thread-a",
        "What did we do for login?",
        max_items=5,
        max_chars=1200,
    )

    assert snippets
    joined = " ".join(s.content.lower() for s in snippets)
    assert "login" in joined
    assert "pasta" not in joined


@pytest.mark.asyncio
async def test_clear_thread_removes_only_selected_thread(tmp_path):
    db_path = tmp_path / "memory.db"
    store = SqliteVecMemoryStore(
        str(db_path),
        embed_model="nomic-embed-text",
        embed_fn=_embed,
        prefer_vec=False,
    )

    await store.initialize()
    await store.add_turn("thread-a", "fix login bug", "resolved login flow")
    await store.add_turn("thread-b", "recipe request", "shared a recipe")

    await store.clear_thread("thread-a")

    a_rows = await store.retrieve_context("thread-a", "login", max_items=5, max_chars=1200)
    b_rows = await store.retrieve_context("thread-b", "recipe", max_items=5, max_chars=1200)

    assert a_rows == []
    assert b_rows


@pytest.mark.asyncio
async def test_add_turn_gracefuly_handles_embedding_failures(tmp_path):
    """Ensure memory writes fail gracefully when embeddings are unavailable."""

    async def fail_embed(_text: str) -> list[float]:
        raise RuntimeError("Embedding model 'nomic-embed-text' not found in Ollama. Pull it with: `ollama pull nomic-embed-text`")

    db_path = tmp_path / "memory.db"
    store = SqliteVecMemoryStore(
        str(db_path),
        embed_model="nomic-embed-text",
        embed_fn=fail_embed,
        prefer_vec=False,
    )

    await store.initialize()

    # Should not raise; should skip gracefully with a warning
    with pytest.warns(UserWarning, match="Memory storage disabled"):
        await store.add_turn("thread-a", "user message", "assistant response")


@pytest.mark.asyncio
async def test_retrieve_context_propagates_embedding_errors(tmp_path):
    """Ensure memory retrieval reports embedding failures clearly."""

    async def fail_embed(_text: str) -> list[float]:
        raise RuntimeError("Embedding model not available")

    db_path = tmp_path / "memory.db"
    store = SqliteVecMemoryStore(
        str(db_path),
        embed_model="nomic-embed-text",
        embed_fn=fail_embed,
        prefer_vec=False,
    )

    await store.initialize()

    with pytest.raises(RuntimeError, match="Cannot retrieve memory"):
        await store.retrieve_context("thread-a", "query", max_items=5, max_chars=1200)

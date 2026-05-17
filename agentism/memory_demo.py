"""Tiny local harness for semantic memory retrieval."""

from __future__ import annotations

import argparse
import asyncio

from agentism import config
from agentism.memory_store import SqliteVecMemoryStore


async def main() -> None:
    parser = argparse.ArgumentParser(description="Memory demo for agentism")
    parser.add_argument("--thread", default="demo", help="Thread id to use")
    parser.add_argument("--query", default="What did we decide?", help="Retrieval query")
    args = parser.parse_args()

    store = SqliteVecMemoryStore(
        config.MEMORY_DB,
        embed_model=config.OLLAMA_EMBED_MODEL,
        chunk_chars=config.MEMORY_CHUNK_CHARS,
        chunk_overlap=config.MEMORY_CHUNK_OVERLAP,
        prefer_vec=True,
    )
    await store.initialize()

    await store.add_turn(args.thread, "User asked to fix login bug", "Implemented fix in auth handler and added tests")
    await store.add_turn(args.thread, "User requested follow-up", "Plan is to verify with pytest and open a PR")

    rows = await store.retrieve_context(
        args.thread,
        args.query,
        max_items=config.MEMORY_RETRIEVAL_LIMIT,
        max_chars=config.MEMORY_CONTEXT_CHAR_BUDGET,
    )

    print(f"Backend: {store.backend_label()} | thread={args.thread}")
    if not rows:
        print("No memory snippets found")
        return
    for idx, row in enumerate(rows, 1):
        print(f"{idx:02d}. [{row.role}] score={row.score:.3f} :: {row.content}")


if __name__ == "__main__":
    asyncio.run(main())


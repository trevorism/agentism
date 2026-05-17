"""Thread-scoped semantic memory stored in SQLite with sqlite-vec when available."""

from __future__ import annotations

import asyncio
import json
import math
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

import httpx

from agentism import config

try:
    import sqlite_vec  # type: ignore
except Exception:  # pragma: no cover - optional dependency at runtime
    sqlite_vec = None


EmbedFn = Callable[[str], Awaitable[list[float]]]


@dataclass(slots=True)
class MemorySnippet:
    """A retrieved memory chunk used to enrich the next prompt."""

    role: str
    content: str
    score: float
    created_at: float


class SqliteVecMemoryStore:
    """Persist and retrieve thread-scoped memory snippets from SQLite."""

    def __init__(
        self,
        db_path: str,
        *,
        embed_model: str,
        embed_fn: EmbedFn | None = None,
        prefer_vec: bool = True,
        chunk_chars: int = 600,
        chunk_overlap: int = 120,
    ) -> None:
        self._db_path = str(db_path)
        self._embed_model = embed_model
        self._embed_fn = embed_fn or self._embed_with_ollama
        self._prefer_vec = prefer_vec
        self._chunk_chars = max(200, chunk_chars)
        self._chunk_overlap = max(0, min(chunk_overlap, self._chunk_chars // 2))
        self._vec_available = bool(prefer_vec and sqlite_vec is not None)
        self._vector_dim: int | None = None

    async def initialize(self) -> None:
        """Create required tables and detect vector backend readiness."""
        await asyncio.to_thread(self._initialize_sync)

    async def add_turn(self, thread_id: str, user_text: str, assistant_text: str) -> None:
        """Persist a turn as user/assistant memory plus a concise assistant summary."""
        await self.initialize()
        now = time.time()
        user_text = (user_text or "").strip()
        assistant_text = (assistant_text or "").strip()
        summary = _summarize_text(assistant_text)

        if user_text:
            await self._add_item(thread_id, "user", user_text, now, importance=0.55)
        if assistant_text:
            await self._add_item(thread_id, "assistant", assistant_text, now, importance=0.65)
        if summary:
            await self._add_item(thread_id, "summary", summary, now, importance=0.85)

    async def retrieve_context(
        self,
        thread_id: str,
        query: str,
        *,
        max_items: int,
        max_chars: int,
    ) -> list[MemorySnippet]:
        """Retrieve the best snippets for a query, scoped strictly to a thread."""
        await self.initialize()
        query_text = (query or "").strip()
        if not query_text:
            return []

        try:
            embedding = await self._embed_fn(query_text)
        except Exception as e:
            raise RuntimeError(f"Cannot retrieve memory: {str(e)}") from e

        if not embedding:
            return []

        raw = await asyncio.to_thread(self._retrieve_sync, thread_id, embedding, max(1, max_items * 4))
        ranked = _rerank(raw)

        selected: list[MemorySnippet] = []
        seen: set[str] = set()
        used = 0
        for row in ranked:
            text = row["content"].strip()
            if not text:
                continue
            dedupe_key = text.lower()
            if dedupe_key in seen:
                continue
            if used + len(text) > max_chars:
                continue
            selected.append(
                MemorySnippet(
                    role=row["role"],
                    content=text,
                    score=row["score"],
                    created_at=row["created_at"],
                )
            )
            seen.add(dedupe_key)
            used += len(text)
            if len(selected) >= max_items:
                break
        return selected

    async def clear_thread(self, thread_id: str) -> None:
        """Remove all semantic memory for a specific thread."""
        await asyncio.to_thread(self._clear_thread_sync, thread_id)

    def backend_label(self) -> str:
        """Return the active retrieval backend for diagnostics."""
        if self._vec_available:
            return "sqlite-vec"
        return "python-cosine"

    async def _add_item(self, thread_id: str, role: str, content: str, created_at: float, importance: float) -> None:
        chunks = _chunk_text(content, self._chunk_chars, self._chunk_overlap)
        if not chunks:
            return

        vectors = []
        errors = []
        for chunk in chunks:
            try:
                vec = await self._embed_fn(chunk)
                vectors.append(vec)
            except Exception as e:
                vectors.append(None)
                errors.append(str(e))

        payload = [(chunk, vec) for chunk, vec in zip(chunks, vectors) if vec]
        if not payload:
            if errors:
                import warnings
                warnings.warn(
                    f"Memory storage disabled: embeddings unavailable. {errors[0][:80]}. "
                    f"See !health for diagnostics."
                )
            return

        await asyncio.to_thread(self._add_item_sync, thread_id, role, content, created_at, importance, payload)

    async def _embed_with_ollama(self, text: str) -> list[float]:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{config.OLLAMA_BASE_URL}/api/embeddings",
                    json={"model": self._embed_model, "prompt": text},
                )
            if resp.status_code == 404:
                raise RuntimeError(
                    f"Embedding model '{self._embed_model}' not found in Ollama. "
                    f"Pull it with: `ollama pull {self._embed_model}`"
                )
            resp.raise_for_status()
            data = resp.json()
            vec = data.get("embedding")
            if not isinstance(vec, list):
                return []
            return [float(v) for v in vec]
        except httpx.ConnectError as e:
            raise RuntimeError(
                f"Cannot connect to Ollama at {config.OLLAMA_BASE_URL}. "
                f"Start Ollama: `ollama serve`"
            ) from e

    def _connect(self) -> sqlite3.Connection:
        path = Path(self._db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _initialize_sync(self) -> None:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    importance REAL NOT NULL DEFAULT 0.5
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL REFERENCES memory_items(id) ON DELETE CASCADE,
                    thread_id TEXT NOT NULL,
                    chunk_text TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    token_estimate INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_chunk_embeddings (
                    chunk_id INTEGER PRIMARY KEY REFERENCES memory_chunks(id) ON DELETE CASCADE,
                    thread_id TEXT NOT NULL,
                    embedding_json TEXT NOT NULL
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_memory_items_thread_time ON memory_items(thread_id, created_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_memory_chunks_thread_time ON memory_chunks(thread_id, created_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_memory_embeddings_thread ON memory_chunk_embeddings(thread_id)")

            dim_row = cur.execute(
                "SELECT embedding_json FROM memory_chunk_embeddings LIMIT 1"
            ).fetchone()
            if dim_row:
                try:
                    self._vector_dim = len(json.loads(dim_row["embedding_json"]))
                except Exception:
                    self._vector_dim = None

            if self._vec_available:
                try:
                    sqlite_vec.load(conn)
                except Exception:
                    self._vec_available = False

            conn.commit()

    def _ensure_vec_table(self, conn: sqlite3.Connection, dim: int) -> None:
        if not self._vec_available:
            return
        sqlite_vec.load(conn)
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS memory_chunk_vec USING vec0(embedding float[{dim}])"
        )

    def _add_item_sync(
        self,
        thread_id: str,
        role: str,
        content: str,
        created_at: float,
        importance: float,
        chunks: list[tuple[str, list[float]]],
    ) -> None:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO memory_items(thread_id, role, content, created_at, importance)
                VALUES(?, ?, ?, ?, ?)
                """,
                (thread_id, role, content, created_at, float(max(0.0, min(1.0, importance)))),
            )
            item_id = int(cur.lastrowid)

            for chunk_text, vec in chunks:
                if self._vector_dim is None:
                    self._vector_dim = len(vec)
                if len(vec) != self._vector_dim:
                    continue

                cur.execute(
                    """
                    INSERT INTO memory_chunks(item_id, thread_id, chunk_text, created_at, token_estimate)
                    VALUES(?, ?, ?, ?, ?)
                    """,
                    (item_id, thread_id, chunk_text, created_at, _approx_tokens(chunk_text)),
                )
                chunk_id = int(cur.lastrowid)

                cur.execute(
                    """
                    INSERT OR REPLACE INTO memory_chunk_embeddings(chunk_id, thread_id, embedding_json)
                    VALUES(?, ?, ?)
                    """,
                    (chunk_id, thread_id, json.dumps(vec)),
                )

                if self._vec_available:
                    try:
                        self._ensure_vec_table(conn, self._vector_dim)
                        blob = sqlite_vec.serialize_float32(vec)
                        cur.execute(
                            "INSERT OR REPLACE INTO memory_chunk_vec(rowid, embedding) VALUES(?, ?)",
                            (chunk_id, blob),
                        )
                    except Exception:
                        self._vec_available = False

            conn.commit()

    def _table_exists(self, conn: sqlite3.Connection, name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?", (name,)
        ).fetchone()
        return bool(row)

    def _retrieve_sync(self, thread_id: str, query_vector: list[float], k: int) -> list[dict]:
        with self._connect() as conn:
            use_vec = self._vec_available and self._table_exists(conn, "memory_chunk_vec")
            if use_vec:
                try:
                    sqlite_vec.load(conn)
                    blob = sqlite_vec.serialize_float32(query_vector)
                    sql = (
                        "SELECT mc.chunk_text, mi.role, mi.created_at, mi.importance, mv.distance "
                        "FROM memory_chunk_vec mv "
                        "JOIN memory_chunks mc ON mc.id = mv.rowid "
                        "JOIN memory_items mi ON mi.id = mc.item_id "
                        "WHERE mv.embedding MATCH ? AND k = ? AND mc.thread_id = ?"
                    )
                    rows = conn.execute(sql, (blob, int(max(1, k)), thread_id)).fetchall()
                    return [
                        {
                            "content": r["chunk_text"],
                            "role": r["role"],
                            "created_at": float(r["created_at"]),
                            "importance": float(r["importance"]),
                            "similarity": 1.0 / (1.0 + float(r["distance"])),
                        }
                        for r in rows
                    ]
                except Exception:
                    self._vec_available = False

            rows = conn.execute(
                """
                SELECT mc.chunk_text, mi.role, mi.created_at, mi.importance, e.embedding_json
                FROM memory_chunk_embeddings e
                JOIN memory_chunks mc ON mc.id = e.chunk_id
                JOIN memory_items mi ON mi.id = mc.item_id
                WHERE mc.thread_id = ?
                ORDER BY mi.created_at DESC
                LIMIT ?
                """,
                (thread_id, max(64, k * 8)),
            ).fetchall()

            result: list[dict] = []
            for row in rows:
                try:
                    vec = json.loads(row["embedding_json"])
                    sim = _cosine_similarity(query_vector, vec)
                except Exception:
                    continue
                result.append(
                    {
                        "content": row["chunk_text"],
                        "role": row["role"],
                        "created_at": float(row["created_at"]),
                        "importance": float(row["importance"]),
                        "similarity": sim,
                    }
                )
            return result

    def _clear_thread_sync(self, thread_id: str) -> None:
        with self._connect() as conn:
            cur = conn.cursor()
            ids = [
                int(r[0])
                for r in cur.execute(
                    "SELECT id FROM memory_chunks WHERE thread_id = ?", (thread_id,)
                ).fetchall()
            ]

            if ids and self._table_exists(conn, "memory_chunk_vec"):
                for chunk_id in ids:
                    cur.execute("DELETE FROM memory_chunk_vec WHERE rowid = ?", (chunk_id,))

            cur.execute("DELETE FROM memory_chunk_embeddings WHERE thread_id = ?", (thread_id,))
            cur.execute("DELETE FROM memory_chunks WHERE thread_id = ?", (thread_id,))
            cur.execute("DELETE FROM memory_items WHERE thread_id = ?", (thread_id,))
            conn.commit()


async def clear_thread_memory(thread_id: str, db_path: str | None = None) -> None:
    """Helper used by commands to clear semantic memory for one thread."""
    store = SqliteVecMemoryStore(
        db_path or config.MEMORY_DB,
        embed_model=config.OLLAMA_EMBED_MODEL,
        prefer_vec=True,
        chunk_chars=config.MEMORY_CHUNK_CHARS,
        chunk_overlap=config.MEMORY_CHUNK_OVERLAP,
    )
    await store.initialize()
    await store.clear_thread(thread_id)


def format_memory_block(snippets: list[MemorySnippet]) -> str:
    """Render snippets into a compact prompt block."""
    if not snippets:
        return ""
    lines = [
        "Use this thread memory as context. Treat it as conversational recall; verify repo/tool facts with tools.",
    ]
    for snip in snippets:
        lines.append(f"- [{snip.role}] {snip.content}")
    return "\n".join(lines)


def _chunk_text(text: str, chunk_chars: int, overlap: int) -> list[str]:
    clean = " ".join((text or "").split())
    if not clean:
        return []
    if len(clean) <= chunk_chars:
        return [clean]

    chunks: list[str] = []
    step = max(1, chunk_chars - overlap)
    idx = 0
    while idx < len(clean):
        raw = clean[idx: idx + chunk_chars]
        if idx + chunk_chars < len(clean):
            split = raw.rfind(" ")
            if split > chunk_chars // 2:
                raw = raw[:split]
        chunk = raw.strip()
        if chunk:
            chunks.append(chunk)
        idx += step
    return chunks


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _summarize_text(text: str) -> str:
    clean = " ".join((text or "").split())
    if not clean:
        return ""
    if len(clean) <= 320:
        return clean
    sentence_end = clean.find(".")
    if 0 < sentence_end <= 320:
        return clean[: sentence_end + 1]
    return clean[:320].rstrip() + "..."


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _rerank(rows: list[dict]) -> list[dict]:
    now = time.time()
    for row in rows:
        age_hours = max(0.0, (now - float(row["created_at"])) / 3600.0)
        recency = 1.0 / (1.0 + (age_hours / 24.0))
        importance = max(0.0, min(1.0, float(row["importance"])))
        similarity = max(0.0, min(1.0, float(row["similarity"])))
        row["score"] = (similarity * 0.72) + (recency * 0.18) + (importance * 0.10)
    rows.sort(key=lambda item: item["score"], reverse=True)
    return rows


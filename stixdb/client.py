"""
StixDB REST client.

    from stixdb import StixDBEngine, StixDBConfig

    engine = StixDBEngine(url="http://localhost:4020", api_key="optional")

    # or:
    config = StixDBConfig.from_env()
    engine = StixDBEngine(config=config)

    async with engine:
        await engine.store("my_agent", "Alice leads payments.")
        response = await engine.ask("my_agent", "Who leads payments?")
        print(response.answer)

This module connects to a running StixDB server started with
``stixdb serve`` or ``stixdb daemon start``.  It does NOT run the graph
engine in-process — all operations are delegated to the server over HTTP.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import httpx


# ── Connection config ─────────────────────────────────────────────────────── #

@dataclass
class StixDBConfig:
    """
    Connection configuration for StixDBEngine.

    Parameters
    ----------
    url:
        Base URL of the running StixDB server (default: http://localhost:4020).
    api_key:
        Optional API key.  Must match ``STIXDB_API_KEY`` on the server.
    timeout:
        Default HTTP timeout in seconds for non-streaming requests.
    """
    url: str = "http://localhost:4020"
    api_key: Optional[str] = None
    timeout: float = 120.0

    @classmethod
    def from_env(cls) -> "StixDBConfig":
        """Read connection settings from environment variables."""
        return cls(
            url=os.getenv("STIXDB_URL", "http://localhost:4020"),
            api_key=os.getenv("STIXDB_API_KEY"),
            timeout=float(os.getenv("STIXDB_TIMEOUT", "120")),
        )


# ── Response wrapper ──────────────────────────────────────────────────────── #

class ContextResponse:
    """
    Returned by :meth:`StixDBEngine.ask`, :meth:`chat`, and
    :meth:`recursive_chat`.

    Attributes
    ----------
    answer:
        Markdown string — structured with ``## headers``, bullet lists,
        inline citations ``[1]`` ``[2]``, and a **Sources** section.
    reasoning_trace:
        Internal chain-of-thought produced by the LLM (not shown to end users).
    sources:
        List of source node dicts used to generate the answer.
    confidence:
        Self-reported float 0–1 confidence.
    model_used:
        LLM model identifier (e.g. ``"gpt-4o"``).
    latency_ms:
        End-to-end server latency in milliseconds.
    is_complete:
        ``False`` when the LLM indicated it needs more information.
    suggested_query:
        Optional follow-up search query suggested by the LLM.
    """

    def __init__(self, data: dict[str, Any]) -> None:
        self.answer: str = str(data.get("answer") or "")
        self.reasoning_trace: str = str(
            data.get("reasoning_trace") or data.get("reasoning") or ""
        )
        self.sources: list[dict[str, Any]] = data.get("sources") or []
        self.confidence: float = float(data.get("confidence") or 0.0)
        self.model_used: str = str(data.get("model_used") or "")
        self.latency_ms: float = float(data.get("latency_ms") or 0.0)
        self.is_complete: bool = bool(data.get("is_complete", True))
        self.suggested_query: Optional[str] = data.get("suggested_query")
        self._raw: dict[str, Any] = data

    def __repr__(self) -> str:
        preview = self.answer[:80].replace("\n", " ")
        return f"ContextResponse(confidence={self.confidence:.2f}, answer={preview!r})"


# ── File types supported for ingestion ───────────────────────────────────── #

_INGEST_SUFFIXES: frozenset[str] = frozenset({
    ".txt", ".md", ".markdown", ".rst", ".log",
    ".csv", ".tsv", ".json", ".jsonl",
    ".yaml", ".yml", ".xml", ".html", ".htm",
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".java", ".c", ".cc", ".cpp", ".h", ".hpp",
    ".cs", ".go", ".rs", ".sh", ".sql",
    ".toml", ".ini", ".cfg", ".conf", ".pdf",
})


# ── Engine (REST client) ──────────────────────────────────────────────────── #

class StixDBEngine:
    """
    REST client for StixDB.  Connects to a running ``stixdb`` server and
    exposes the same interface as the in-process engine so that application
    code does not need to change when switching between embedded and
    server-backed deployments.

    Usage::

        # Explicit URL
        engine = StixDBEngine(url="http://localhost:4020", api_key="secret")

        # From environment  (STIXDB_URL, STIXDB_API_KEY, STIXDB_TIMEOUT)
        engine = StixDBEngine(config=StixDBConfig.from_env())

        # Context manager (recommended)
        async with StixDBEngine() as engine:
            await engine.store("proj", "Alice leads payments.")
            response = await engine.ask("proj", "Who leads payments?")
            print(response.answer)
    """

    def __init__(
        self,
        url: str = "http://localhost:4020",
        api_key: Optional[str] = None,
        timeout: float = 120.0,
        *,
        config: Optional[StixDBConfig] = None,
    ) -> None:
        if config is not None:
            url = config.url
            api_key = config.api_key
            timeout = config.timeout

        self._base = url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            self._headers["X-API-Key"] = api_key

        self._sync = httpx.Client(
            base_url=self._base,
            headers=self._headers,
            timeout=timeout,
        )
        self._async = httpx.AsyncClient(
            base_url=self._base,
            headers=self._headers,
            timeout=timeout,
        )

    # ── lifecycle ─────────────────────────────────────────────────────────── #

    async def start(self) -> None:
        """Validate the connection by calling ``GET /health``."""
        resp = await self._async.get("/health")
        resp.raise_for_status()

    async def stop(self) -> None:
        """Close all open HTTP connections."""
        await self._async.aclose()
        self._sync.close()

    async def __aenter__(self) -> "StixDBEngine":
        await self.start()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.stop()

    # ── internal helpers ──────────────────────────────────────────────────── #

    async def _post(self, path: str, *, body: dict[str, Any]) -> dict[str, Any]:
        resp = await self._async.post(path, json=body)
        resp.raise_for_status()
        return resp.json()

    async def _get(self, path: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        resp = await self._async.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def _delete(self, path: str) -> dict[str, Any]:
        resp = await self._async.delete(path)
        resp.raise_for_status()
        return resp.json()

    async def _sse(
        self,
        path: str,
        body: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        """POST *path* and yield parsed JSON objects from an SSE response."""
        # Use a longer timeout for streaming — answers can take a while.
        async with httpx.AsyncClient(
            base_url=self._base,
            headers=self._headers,
            timeout=max(self._timeout, 300.0),
        ) as client:
            async with client.stream("POST", path, json=body) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload == "[DONE]":
                        return
                    try:
                        yield json.loads(payload)
                    except json.JSONDecodeError:
                        pass

    # ── store ─────────────────────────────────────────────────────────────── #

    async def store(
        self,
        collection: str,
        content: str,
        *,
        node_type: str = "fact",
        tier: str = "episodic",
        importance: float = 0.7,
        pinned: bool = False,
        source: Optional[str] = None,
        source_agent_id: Optional[str] = None,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        node_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Store a single memory node."""
        return await self._post(
            f"/collections/{collection}/nodes",
            body={
                "id": node_id,
                "content": content,
                "node_type": node_type,
                "tier": tier,
                "importance": importance,
                "pinned": pinned,
                "source": source,
                "source_agent_id": source_agent_id,
                "tags": tags or [],
                "metadata": metadata or {},
            },
        )

    async def bulk_store(
        self,
        collection: str,
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Store multiple memory nodes in a single request."""
        resp = await self._async.post(
            f"/collections/{collection}/nodes/bulk",
            json=items,
        )
        resp.raise_for_status()
        return resp.json()

    # ── ingest ────────────────────────────────────────────────────────────── #

    async def ingest_file(
        self,
        collection: str,
        filepath: str | Path,
        *,
        tags: Optional[list[str]] = None,
        chunk_size: int = 600,
        chunk_overlap: int = 150,
        parser: str = "auto",
        source_name: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Upload and ingest a local file into a collection.

        The file is chunked server-side.  Duplicate chunks are silently
        deduplicated by content hash so re-ingesting an unchanged file is safe.
        """
        path = Path(filepath)
        upload_headers: dict[str, str] = {}
        if self._api_key:
            upload_headers["X-API-Key"] = self._api_key

        with path.open("rb") as fh:
            resp = await self._async.post(
                f"/collections/{collection}/upload",
                files={"file": (source_name or path.name, fh)},
                data={
                    "tags": ",".join(tags or []),
                    "chunk_size": str(chunk_size),
                    "chunk_overlap": str(chunk_overlap),
                    "parser": parser,
                },
                headers=upload_headers,
            )
        resp.raise_for_status()
        return resp.json()

    async def ingest_folder(
        self,
        collection: str,
        folderpath: str | Path,
        *,
        tags: Optional[list[str]] = None,
        chunk_size: int = 600,
        chunk_overlap: int = 150,
        parser: str = "auto",
        recursive: bool = True,
    ) -> dict[str, Any]:
        """
        Ingest all supported files in a local directory.

        Files are uploaded one at a time.  Skipped files (binary, unsupported
        extensions) are listed in the returned ``"skipped"`` key.
        """
        root = Path(folderpath)
        if not root.exists():
            raise FileNotFoundError(f"Folder not found: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"Not a directory: {root}")

        iterator = root.rglob("*") if recursive else root.glob("*")
        ingested: list[dict[str, Any]] = []
        skipped: list[str] = []

        for path in sorted(iterator):
            if not path.is_file():
                continue
            if path.suffix.lower() not in _INGEST_SUFFIXES:
                skipped.append(str(path))
                continue
            rel = str(path.relative_to(root))
            result = await self.ingest_file(
                collection,
                path,
                tags=tags,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                parser=parser,
                source_name=rel,
            )
            ingested.append({"filepath": str(path), "relative_path": rel, "result": result})

        return {
            "collection": collection,
            "folder": str(root),
            "files_processed": len(ingested),
            "files_skipped": len(skipped),
            "ingested": ingested,
            "skipped": skipped,
        }

    # ── retrieve ──────────────────────────────────────────────────────────── #

    async def retrieve(
        self,
        collection: str,
        query: str,
        *,
        top_k: int = 10,
        threshold: float = 0.1,
        depth: int = 1,
        mode: str = "hybrid",
    ) -> list[dict[str, Any]]:
        """
        Raw retrieval without LLM reasoning.

        Parameters
        ----------
        mode:
            ``"hybrid"`` (default) — keyword + semantic merged.
            ``"keyword"`` — tag/term match only, no embedding API call.
            ``"semantic"`` — vector similarity only.
        """
        data = await self._post(
            f"/collections/{collection}/retrieve",
            body={"query": query, "top_k": top_k, "threshold": threshold, "depth": depth, "mode": mode},
        )
        return data.get("results", [])

    # ── ask / chat ────────────────────────────────────────────────────────── #

    async def ask(
        self,
        collection: str,
        question: str,
        *,
        top_k: int = 15,
        threshold: float = 0.2,
        depth: int = 2,
        thinking_steps: int = 1,
        hops_per_step: int = 4,
        system_prompt: Optional[str] = None,
        output_schema: Optional[dict[str, Any]] = None,
        max_tokens: Optional[int] = None,
    ) -> ContextResponse:
        """
        Ask a question and receive a synthesised Markdown answer with citations.

        Set ``thinking_steps > 1`` for multi-hop autonomous reasoning — the
        engine will perform multiple retrieval cycles, refining its search
        angle at each step before synthesising a final answer.

        Returns a :class:`ContextResponse` whose ``.answer`` field is
        Markdown with inline citations ``[1]`` ``[2]`` and a **Sources** section.
        """
        payload: dict[str, Any] = {
            "question": question,
            "top_k": top_k,
            "threshold": threshold,
            "depth": depth,
            "thinking_steps": thinking_steps,
            "hops_per_step": hops_per_step,
            "system_prompt": system_prompt,
            "output_schema": output_schema,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        data = await self._post(f"/collections/{collection}/ask", body=payload)
        return ContextResponse(data)

    async def chat(
        self,
        collection: str,
        question: str,
        *,
        session_id: Optional[str] = None,
        top_k: int = 15,
        depth: int = 2,
        max_tokens: Optional[int] = None,
    ) -> ContextResponse:
        """Single-turn chat.  Delegates to :meth:`ask`."""
        return await self.ask(
            collection,
            question,
            top_k=top_k,
            depth=depth,
            max_tokens=max_tokens,
        )

    async def recursive_chat(
        self,
        collection: str,
        question: str,
        *,
        session_id: Optional[str] = None,
        thinking_steps: int = 2,
        hops_per_step: int = 4,
        top_k: int = 20,
        depth: int = 3,
        max_tokens: Optional[int] = None,
    ) -> ContextResponse:
        """
        Multi-hop reasoning over a single question.

        Equivalent to :meth:`ask` with ``thinking_steps > 1``.  The engine
        performs multiple retrieval-reasoning cycles and synthesises the
        deepest possible answer before returning.
        """
        return await self.ask(
            collection,
            question,
            top_k=top_k,
            depth=depth,
            thinking_steps=thinking_steps,
            hops_per_step=hops_per_step,
            max_tokens=max_tokens,
        )

    # ── streaming ─────────────────────────────────────────────────────────── #

    async def stream_chat(
        self,
        collection: str,
        question: str,
        *,
        session_id: Optional[str] = None,
        top_k: int = 15,
        threshold: float = 0.2,
        depth: int = 2,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Stream answer tokens as they are generated.

        Yields dicts::

            {"type": "node_count", "count": 12}          # once, before first token
            {"type": "answer",     "content": "## Auth"} # repeatedly
            ...

        Example::

            async for chunk in engine.stream_chat("proj", "Explain auth"):
                if chunk["type"] == "answer":
                    print(chunk["content"], end="", flush=True)
        """
        payload: dict[str, Any] = {
            "question": question,
            "top_k": top_k,
            "threshold": threshold,
            "depth": depth,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        async for chunk in self._sse(f"/collections/{collection}/ask/stream", payload):
            yield chunk

    async def stream_recursive_chat(
        self,
        collection: str,
        question: str,
        *,
        session_id: Optional[str] = None,
        thinking_steps: int = 2,
        hops_per_step: int = 4,
        top_k: int = 20,
        depth: int = 3,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Stream a multi-hop reasoning answer token by token.

        In addition to ``"answer"`` chunks, may emit ``"thinking"`` chunks
        (short narrator thoughts between hops) and ``"node_count"`` chunks.
        """
        payload: dict[str, Any] = {
            "question": question,
            "top_k": top_k,
            "threshold": 0.2,
            "depth": depth,
            "thinking_steps": thinking_steps,
            "hops_per_step": hops_per_step,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        async for chunk in self._sse(f"/collections/{collection}/ask/stream", payload):
            yield chunk

    # ── search ────────────────────────────────────────────────────────────── #

    async def search(
        self,
        collection: str,
        query: str,
        *,
        top_k: int = 10,
        depth: int = 1,
        threshold: float = 0.1,
        mode: str = "hybrid",
        tags: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """
        Search a collection without LLM reasoning.

        Faster than :meth:`ask` — use when you want ranked nodes back directly.
        """
        data = await self._post(
            "/search",
            body={
                "query": query,
                "collection": collection,
                "top_k": top_k,
                "max_results": top_k,
                "depth": depth,
                "threshold": threshold,
                "search_mode": mode,
                "tag_filter": tags or [],
            },
        )
        return data.get("results", [])

    # ── relations ─────────────────────────────────────────────────────────── #

    async def add_relation(
        self,
        collection: str,
        source_node_id: str,
        target_node_id: str,
        *,
        relation_type: str = "related_to",
        weight: float = 1.0,
        confidence: float = 1.0,
        created_by: str = "user",
        metadata: Optional[dict[str, Any]] = None,
        edge_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create an explicit typed edge between two nodes."""
        return await self._post(
            f"/collections/{collection}/relations",
            body={
                "id": edge_id,
                "source_node_id": source_node_id,
                "target_node_id": target_node_id,
                "relation_type": relation_type,
                "weight": weight,
                "confidence": confidence,
                "created_by": created_by,
                "metadata": metadata or {},
            },
        )

    # ── stats ─────────────────────────────────────────────────────────────── #

    async def get_graph_stats(self, collection: str) -> dict[str, Any]:
        """Return graph statistics (node/edge counts, tier breakdown)."""
        return await self._get(f"/collections/{collection}/stats")

    async def get_collection_stats(self, collection: str) -> dict[str, Any]:
        """Alias for :meth:`get_graph_stats`."""
        return await self._get(f"/collections/{collection}/stats")

    # ── collection management ─────────────────────────────────────────────── #

    def list_collections(self) -> list[str]:
        """Return all collection names (synchronous)."""
        resp = self._sync.get("/health")
        resp.raise_for_status()
        return resp.json().get("collections", [])

    async def list_collections_async(self) -> list[str]:
        """Return all collection names (async)."""
        data = await self._get("/health")
        return data.get("collections", [])

    async def delete_collection(self, collection: str) -> dict[str, Any]:
        """Permanently delete all data for a collection."""
        return await self._delete(f"/collections/{collection}")

    async def drop_collection(self, collection: str) -> None:
        """Alias for :meth:`delete_collection`."""
        await self.delete_collection(collection)

    async def dedupe_collection(
        self,
        collection: str,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Remove duplicate nodes.  Pass ``dry_run=True`` to preview."""
        resp = await self._async.post(
            f"/collections/{collection}/dedupe",
            params={"dry_run": dry_run},
        )
        resp.raise_for_status()
        return resp.json()

    # ── agent ─────────────────────────────────────────────────────────────── #

    async def trigger_agent_cycle(self, collection: str) -> dict[str, Any]:
        """Manually run a consolidation / decay cycle for a collection."""
        resp = await self._async.post(f"/collections/{collection}/agent/cycle")
        resp.raise_for_status()
        return resp.json()

    async def get_agent_status(self, collection: str) -> dict[str, Any]:
        """Return the background agent's current state and statistics."""
        return await self._get(f"/collections/{collection}/agent/status")

    # ── observability ─────────────────────────────────────────────────────── #

    def get_traces(self, collection: str, *, limit: int = 10) -> list[Any]:
        """Traces are not exposed via REST. Returns an empty list."""
        return []

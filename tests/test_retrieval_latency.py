from __future__ import annotations

import hashlib
import re
import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

from stixdb.api.routes.query import RetrieveRequest, retrieve
from stixdb.agent.memory_agent import MemoryAgent
from stixdb.config import (
    AgentConfig,
    EmbeddingConfig,
    EmbeddingProvider,
    LLMProvider,
    ReasonerConfig,
    StixDBConfig,
    StorageConfig,
    StorageMode,
    VectorBackend,
)
from stixdb.engine import StixDBEngine
from stixdb.graph.edge import RelationType
from stixdb.graph.node import MemoryTier, NodeType
from stixdb.graph.summary_index import (
    build_connection_entries,
    build_summary_connection_index,
    extract_summary_related_node_ids,
    merge_summary_connection_index,
)
from stixdb_sdk import AsyncStixDBClient, StixDBClient


class DummyEmbeddingClient:
    def __init__(self, dimensions: int = 32) -> None:
        self.dimensions = dimensions

    def _embed(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dimensions, dtype=np.float32)
        for token in re.findall(r"[a-zA-Z0-9_]+", text.lower()):
            digest = hashlib.sha1(token.encode("utf-8")).digest()
            index = digest[0] % self.dimensions
            vec[index] += 1.0
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.astype(np.float32)

    async def embed_text(self, text: str) -> np.ndarray:
        return self._embed(text)

    async def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        return [self._embed(text) for text in texts]

    async def close(self) -> None:
        return None


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(
        "stixdb.engine.build_embedding_client",
        lambda config: DummyEmbeddingClient(),
    )

    async def _noop_start(self) -> None:
        return None

    async def _noop_stop(self) -> None:
        return None

    monkeypatch.setattr(MemoryAgent, "start", _noop_start)
    monkeypatch.setattr(MemoryAgent, "stop", _noop_stop)

    config = StixDBConfig(
        agent=AgentConfig(enable_predictive_prefetch=False, enable_relation_weaving=False),
        reasoner=ReasonerConfig(provider=LLMProvider.NONE),
        storage=StorageConfig(
            mode=StorageMode.MEMORY,
            vector_backend=VectorBackend.MEMORY,
        ),
        embedding=EmbeddingConfig(provider=EmbeddingProvider.CUSTOM, dimensions=32),
        enable_metrics=False,
        enable_traces=False,
        verbose=False,
    )

    engine = StixDBEngine(config=config)
    asyncio.run(engine.start())
    try:
        yield engine
    finally:
        asyncio.run(engine.stop())


def test_retrieve_route_returns_latency_and_uses_summary_metadata(engine, monkeypatch):
    async def _exercise() -> None:
        collection = "latency-check"
        graph, _, _ = await engine._ensure_collection(collection)

        async def fail_bfs(*args, **kwargs):
            raise AssertionError("graph BFS should not run when summary metadata is available")

        monkeypatch.setattr(graph._storage, "get_neighbours_for_nodes", fail_bfs)

        related_a = await graph.add_node(
            content="beta relation chunk one",
            node_type=NodeType.FACT,
            tier=MemoryTier.WORKING,
            importance=0.4,
            source="test",
            tags=["beta"],
            metadata={"kind": "related"},
            pinned=False,
        )
        related_b = await graph.add_node(
            content="gamma relation chunk two",
            node_type=NodeType.FACT,
            tier=MemoryTier.WORKING,
            importance=0.4,
            source="test",
            tags=["gamma"],
            metadata={"kind": "related"},
            pinned=False,
        )
        summary = await graph.add_node(
            content="alpha summary primary",
            node_type=NodeType.SUMMARY,
            tier=MemoryTier.WORKING,
            importance=0.9,
            source="agent-maintenance",
            tags=["summary"],
            metadata={"summary_kind": "manual"},
            parent_node_ids=[related_a.id, related_b.id],
            pinned=False,
        )
        summary.metadata["connection_index"] = build_summary_connection_index(
            summary_id=summary.id,
            summary_kind="manual",
            source="agent-maintenance",
            content_hash=engine._hash_text(summary.content),
            entries=build_connection_entries(
                [related_a.id, related_b.id],
                relation_type=RelationType.SUMMARIZES,
                role="support",
                weight=1.0,
                source="agent-maintenance",
            ),
        )
        await graph.update_node(summary)

        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(engine=engine)))
        response = await retrieve(
            collection=collection,
            body=RetrieveRequest(query="alpha summary primary", top_k=1, threshold=0.0, depth=1),
            request=request,
        )

        assert "latency_ms" in response
        assert response["latency_ms"] >= 0.0
        returned_ids = {item["id"] for item in response["results"]}
        assert summary.id in returned_ids
        assert related_a.id in returned_ids or related_b.id in returned_ids

    asyncio.run(_exercise())


def test_summary_connection_index_helpers_cover_new_and_legacy_fields():
    base_index = build_summary_connection_index(
        summary_id="summary-a",
        summary_kind="manual",
        source="agent-maintenance",
        content_hash="abc123",
        entries=build_connection_entries(
            ["node-1", "node-2"],
            relation_type=RelationType.SUMMARIZES,
            role="support",
            weight=1.0,
            source="agent-maintenance",
        ),
    )
    merged_index = merge_summary_connection_index(
        {
            "connection_index": base_index,
            "synthesized_from": ["node-3"],
            "focus_node_ids": ["node-4"],
            "source_lineage": [{"node_id": "node-5", "source": "test"}],
        },
        summary_id="summary-a",
        summary_kind="manual",
        source="agent-maintenance",
        content_hash="abc123",
        entries=build_connection_entries(
            ["node-6"],
            relation_type=RelationType.DERIVED_FROM,
            role="absorbed",
            weight=0.7,
            source="agent-maintenance",
        ),
    )
    ids = extract_summary_related_node_ids({"connection_index": merged_index})
    assert len(ids) == len(set(ids))
    assert "summary-a" not in ids
    assert {"node-1", "node-2", "node-3", "node-4", "node-5", "node-6"}.issubset(set(ids))


def test_sync_query_helper_forces_vector_only_depth():
    client = StixDBClient(base_url="http://example.com")
    captured: dict[str, object] = {}

    def fake_request(method: str, path: str, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured["json"] = kwargs["json"]
        return {"collection": "demo", "query": "hello", "results": [], "count": 0, "latency_ms": 1.2}

    client._request = fake_request  # type: ignore[method-assign]

    response = client.query.retrieve_vector_only("demo", query="hello", top_k=4, threshold=0.1)
    client.close()

    assert response["latency_ms"] == 1.2
    assert captured["method"] == "POST"
    assert captured["path"] == "/collections/demo/retrieve"
    assert captured["json"]["depth"] == 0


def test_async_query_helper_forces_vector_only_depth():
    async def _exercise() -> None:
        client = AsyncStixDBClient(base_url="http://example.com")
        captured: dict[str, object] = {}

        async def fake_request(method: str, path: str, **kwargs):
            captured["method"] = method
            captured["path"] = path
            captured["json"] = kwargs["json"]
            return {"collection": "demo", "query": "hello", "results": [], "count": 0, "latency_ms": 1.2}

        client._request = fake_request  # type: ignore[method-assign]

        response = await client.query.retrieve_vector_only("demo", query="hello", top_k=4, threshold=0.1)
        await client.aclose()

        assert response["latency_ms"] == 1.2
        assert captured["method"] == "POST"
        assert captured["path"] == "/collections/demo/retrieve"
        assert captured["json"]["depth"] == 0

    asyncio.run(_exercise())

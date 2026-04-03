"""
VectorStore — unified embedding + semantic search layer.

Supports three backends:
  1. MEMORY — pure numpy cosine similarity (zero deps, good for <100k nodes)
  2. CHROMA — ChromaDB embedded vector database
  3. QDRANT — Qdrant high-performance vector database

The VectorStore is the ONLY component that touches embeddings.
All other components deal with MemoryNode objects and node IDs.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import numpy as np

from stixdb.config import VectorBackend


class VectorSearchResult:
    """A single semantic search result."""
    __slots__ = ("node_id", "score", "content")

    def __init__(self, node_id: str, score: float, content: str = "") -> None:
        self.node_id = node_id
        self.score = score
        self.content = content

    def __repr__(self) -> str:
        return f"VectorSearchResult(node={self.node_id[:8]}..., score={self.score:.4f})"



# ──────────────────────────────────────────────────────────────────────────── #
# In-memory numpy vector store                                                 #
# ──────────────────────────────────────────────────────────────────────────── #

class MemoryVectorStore:
    """
    Pure numpy cosine similarity search.
    O(n) scan — suitable up to ~500k nodes.
    """

    def __init__(self) -> None:
        # collection -> {node_id: (embedding_array, content_str)}
        self._store: dict[str, dict[str, tuple[np.ndarray, str]]] = {}

    async def upsert(self, collection: str, node_id: str, embedding: np.ndarray, content: str) -> None:
        if collection not in self._store:
            self._store[collection] = {}
        self._store[collection][node_id] = (embedding, content)

    async def delete(self, collection: str, node_id: str) -> None:
        self._store.get(collection, {}).pop(node_id, None)

    async def delete_collection(self, collection: str) -> None:
        self._store.pop(collection, None)

    async def search(
        self, collection: str, query_embedding: np.ndarray, top_k: int = 10, threshold: float = 0.0
    ) -> list[VectorSearchResult]:
        store = self._store.get(collection, {})
        if not store:
            return []

        ids = list(store.keys())
        matrix = np.stack([store[i][0] for i in ids])          # (N, D)
        scores = matrix @ query_embedding                        # cosine similarity (embeddings are normalised)

        top_indices = np.argsort(scores)[::-1][:top_k]
        results = []
        for idx in top_indices:
            score = float(scores[idx])
            if score >= threshold:
                results.append(VectorSearchResult(
                    node_id=ids[idx],
                    score=score,
                    content=store[ids[idx]][1],
                ))
        return results

    async def close(self) -> None:
        self._store.clear()


# ──────────────────────────────────────────────────────────────────────────── #
# ChromaDB vector store                                                        #
# ──────────────────────────────────────────────────────────────────────────── #

class ChromaVectorStore:
    """ChromaDB-backed vector store. Supports local persistence."""

    def __init__(self, data_dir: Optional[str] = None, host: Optional[str] = None) -> None:
        self.data_dir = data_dir
        self.host = host
        self._client = None
        self._collections: dict[str, Any] = {}

    def _get_client(self):
        if self._client is None:
            import chromadb
            if self.host:
                self._client = chromadb.HttpClient(host=self.host)
            elif self.data_dir:
                self._client = chromadb.PersistentClient(path=self.data_dir)
            else:
                self._client = chromadb.EphemeralClient()
        return self._client

    def _get_collection(self, collection: str):
        if collection not in self._collections:
            client = self._get_client()
            self._collections[collection] = client.get_or_create_collection(
                name=f"stix_{collection}",
                metadata={"hnsw:space": "cosine"},
            )
        return self._collections[collection]

    async def upsert(self, collection: str, node_id: str, embedding: np.ndarray, content: str) -> None:
        col = self._get_collection(collection)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: col.upsert(
                ids=[node_id],
                embeddings=[embedding.tolist()],
                documents=[content],
            )
        )

    async def delete(self, collection: str, node_id: str) -> None:
        col = self._get_collection(collection)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: col.delete(ids=[node_id]))

    async def delete_collection(self, collection: str) -> None:
        client = self._get_client()
        name = f"stix_{collection}"
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, lambda: client.delete_collection(name))
        except Exception:
            pass
        self._collections.pop(collection, None)

    async def search(
        self, collection: str, query_embedding: np.ndarray, top_k: int = 10, threshold: float = 0.0
    ) -> list[VectorSearchResult]:
        col = self._get_collection(collection)
        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(
            None,
            lambda: col.query(
                query_embeddings=[query_embedding.tolist()],
                n_results=top_k,
                include=["distances", "documents"],
            )
        )
        results = []
        for node_id, dist, doc in zip(
            raw["ids"][0], raw["distances"][0], raw["documents"][0]
        ):
            score = 1.0 - dist  # Chroma returns L2 distance; approximate cosine conversion
            if score >= threshold:
                results.append(VectorSearchResult(node_id=node_id, score=score, content=doc))
        return results

    async def close(self) -> None:
        self._collections.clear()
        self._client = None


# ──────────────────────────────────────────────────────────────────────────── #
# Qdrant vector store                                                          #
# ──────────────────────────────────────────────────────────────────────────── #

class QdrantVectorStore:
    """Qdrant-backed high-performance vector store."""

    EMBEDDING_DIM = 384  # all-MiniLM-L6-v2 dimension

    def __init__(self, host: str = "localhost", port: int = 6333) -> None:
        self.host = host
        self.port = port
        self._client = None

    def _get_client(self):
        if self._client is None:
            from qdrant_client import QdrantClient
            self._client = QdrantClient(host=self.host, port=self.port)
        return self._client

    def _ensure_collection(self, collection: str) -> None:
        from qdrant_client import models as qm
        client = self._get_client()
        col_name = f"stix_{collection}"
        try:
            client.get_collection(col_name)
        except Exception:
            client.create_collection(
                collection_name=col_name,
                vectors_config=qm.VectorParams(
                    size=self.EMBEDDING_DIM,
                    distance=qm.Distance.COSINE
                ),
            )

    async def upsert(self, collection: str, node_id: str, embedding: np.ndarray, content: str) -> None:
        from qdrant_client import models as qm
        self._ensure_collection(collection)
        client = self._get_client()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: client.upsert(
                collection_name=f"stix_{collection}",
                points=[qm.PointStruct(
                    id=abs(hash(node_id)) % (2**63),
                    vector=embedding.tolist(),
                    payload={"node_id": node_id, "content": content},
                )]
            )
        )

    async def delete(self, collection: str, node_id: str) -> None:
        from qdrant_client import models as qm
        client = self._get_client()
        loop = asyncio.get_event_loop()
        point_id = abs(hash(node_id)) % (2**63)
        await loop.run_in_executor(
            None,
            lambda: client.delete(
                collection_name=f"stix_{collection}",
                points_selector=qm.PointIdsList(points=[point_id]),
            )
        )

    async def delete_collection(self, collection: str) -> None:
        client = self._get_client()
        name = f"stix_{collection}"
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, lambda: client.delete_collection(name))
        except Exception:
            pass

    async def search(
        self, collection: str, query_embedding: np.ndarray, top_k: int = 10, threshold: float = 0.0
    ) -> list[VectorSearchResult]:
        self._ensure_collection(collection)
        client = self._get_client()
        loop = asyncio.get_event_loop()
        hits = await loop.run_in_executor(
            None,
            lambda: client.query_points(
                collection_name=f"stix_{collection}",
                query=query_embedding.tolist(),
                limit=top_k,
                score_threshold=threshold,
            )
        )
        return [
            VectorSearchResult(
                node_id=h.payload["node_id"],
                score=h.score,
                content=h.payload.get("content", ""),
            )
            for h in hits.points
        ]

    async def close(self) -> None:
        self._client = None


# ──────────────────────────────────────────────────────────────────────────── #
# Factory                                                                      #
# ──────────────────────────────────────────────────────────────────────────── #

def build_vector_store(
    backend: VectorBackend,
    data_dir: Optional[str] = None,
    chroma_host: Optional[str] = None,
    qdrant_host: str = "localhost",
    qdrant_port: int = 6333,
) -> "MemoryVectorStore | ChromaVectorStore | QdrantVectorStore":
    if backend == VectorBackend.MEMORY:
        return MemoryVectorStore()
    elif backend == VectorBackend.CHROMA:
        return ChromaVectorStore(data_dir=data_dir, host=chroma_host)
    elif backend == VectorBackend.QDRANT:
        return QdrantVectorStore(host=qdrant_host, port=qdrant_port)
    else:
        raise ValueError(f"Unknown vector backend: {backend}")

"""
MemoryGraph — high-level graph operations over the storage + vector layers.

This is the unified API that the Memory Agent and Context Broker use.
It coordinates between the StorageBackend (graph topology) and the
VectorStore (semantic search), keeping them in sync.
"""
from __future__ import annotations

import hashlib
import re
import time
from typing import Optional, Union

from stixdb.graph.node import MemoryNode, NodeType, MemoryTier
from stixdb.graph.edge import RelationEdge, RelationType
from stixdb.graph.cluster import MemoryCluster, ClusterType
from stixdb.storage.base import StorageBackend
from stixdb.storage.embeddings import EmbeddingClient
from stixdb.storage.vector_store import VectorSearchResult


class MemoryGraph:
    """
    High-level graph interface.
    
    Wraps a StorageBackend + VectorStore and exposes an ergonomic API
    for all StixDB components. This is the single point of truth for
    what exists in the graph.
    """

    def __init__(
        self,
        collection: str,
        storage: StorageBackend,
        vector_store,
        embedding_client: EmbeddingClient,
    ) -> None:
        self.collection = collection
        self._storage = storage
        self._vector_store = vector_store
        self._embedding_client = embedding_client

    # ------------------------------------------------------------------ #
    # Initialisation                                                       #
    # ------------------------------------------------------------------ #

    async def initialize(self) -> None:
        await self._storage.initialize(self.collection)
        existing_nodes = await self._storage.list_nodes(self.collection, limit=1_000_000, offset=0)
        for node in existing_nodes:
            embedding = node.get_embedding_array()
            if embedding is None:
                embedding = await self._embedding_client.embed_text(node.content)
                node.set_embedding(embedding)
                await self._storage.upsert_node(node)
            await self._vector_store.upsert(
                collection=self.collection,
                node_id=node.id,
                embedding=embedding,
                content=node.content,
            )

    # ------------------------------------------------------------------ #
    # Node Operations                                                      #
    # ------------------------------------------------------------------ #

    async def add_node(
        self,
        content: str,
        node_type: NodeType = NodeType.FACT,
        tier: MemoryTier = MemoryTier.EPISODIC,
        importance: float = 0.5,
        source: Optional[str] = None,
        source_agent_id: Optional[str] = None,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict] = None,
        pinned: bool = False,
        node_id: Optional[str] = None,
    ) -> MemoryNode:
        """Create, embed, and persist a new MemoryNode."""
        node = MemoryNode(
            id=node_id or MemoryNode.model_fields["id"].default_factory(),
            collection=self.collection,
            content=content,
            node_type=node_type,
            tier=tier,
            importance=importance,
            source=source,
            source_agent_id=source_agent_id,
            tags=tags or [],
            metadata=metadata or {},
            pinned=pinned,
        )
        # Compute embedding
        embedding = await self._embedding_client.embed_text(content)
        node.set_embedding(embedding)

        # Persist in both graph + vector store atomically
        await self._storage.upsert_node(node)
        await self._vector_store.upsert(
            collection=self.collection,
            node_id=node.id,
            embedding=embedding,
            content=content,
        )
        return node

    async def get_node(self, node_id: str) -> Optional[MemoryNode]:
        return await self._storage.get_node(node_id, self.collection)

    async def update_node(self, node: MemoryNode) -> None:
        """Persist changes to an existing MemoryNode. Re-embeds if content changed."""
        await self._storage.upsert_node(node)

    async def touch_node(self, node_id: str) -> Optional[MemoryNode]:
        """Record a read access on a node."""
        node = await self._storage.get_node(node_id, self.collection)
        if node:
            node.touch()
            await self._storage.upsert_node(node)
        return node

    async def delete_node(self, node_id: str) -> bool:
        ok = await self._storage.delete_node(node_id, self.collection)
        if ok:
            await self._vector_store.delete(self.collection, node_id)
        return ok

    async def delete_collection(self) -> bool:
        storage_deleted = await self._storage.delete_collection(self.collection)
        await self._vector_store.delete_collection(self.collection)
        return storage_deleted

    async def list_nodes(
        self,
        tier: Optional[str] = None,
        node_type: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[MemoryNode]:
        return await self._storage.list_nodes(
            self.collection, tier=tier, node_type=node_type, limit=limit, offset=offset
        )

    async def count_nodes(self) -> int:
        return await self._storage.count_nodes(self.collection)

    # ------------------------------------------------------------------ #
    # Edge Operations                                                      #
    # ------------------------------------------------------------------ #

    async def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation_type: RelationType = RelationType.RELATES_TO,
        weight: float = 1.0,
        confidence: float = 1.0,
        created_by: str = "system",
        metadata: Optional[dict] = None,
        edge_id: Optional[str] = None,
    ) -> RelationEdge:
        safe_weight = max(0.0, min(1.0, float(weight)))
        safe_confidence = max(0.0, min(1.0, float(confidence)))
        edge = RelationEdge(
            id=edge_id or RelationEdge.model_fields["id"].default_factory(),
            collection=self.collection,
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            weight=safe_weight,
            confidence=safe_confidence,
            created_by=created_by,
            metadata=metadata or {},
        )
        await self._storage.upsert_edge(edge)
        return edge

    async def delete_edge(self, edge_id: str) -> bool:
        return await self._storage.delete_edge(edge_id, self.collection)

    async def get_neighbours(
        self,
        node_id: str,
        direction: str = "both",
        relation_types: Optional[list[str]] = None,
        max_depth: int = 1,
    ) -> list[MemoryNode]:
        return await self._storage.get_neighbours(
            node_id, self.collection, direction, relation_types, max_depth
        )

    async def get_edges(self, node_id: str, direction: str = "both") -> list[RelationEdge]:
        return await self._storage.get_edges_for_node(node_id, self.collection, direction)

    # ------------------------------------------------------------------ #
    # Semantic Search                                                      #
    # ------------------------------------------------------------------ #

    async def semantic_search(
        self,
        query: str,
        top_k: int = 10,
        threshold: float = 0.3,
    ) -> list[tuple[MemoryNode, float]]:
        """
        Embed the query, search the vector store, then fetch full MemoryNodes.
        Returns (node, score) pairs sorted by descending score.
        """
        query_embedding = await self._embedding_client.embed_text(query)
        hits = await self._vector_store.search(
            collection=self.collection,
            query_embedding=query_embedding,
            top_k=top_k,
            threshold=threshold,
        )
        nodes = await self._storage.get_nodes(
            [hit.node_id for hit in hits],
            self.collection,
        )
        node_map = {node.id: node for node in nodes}
        results = []
        for hit in hits:
            node = node_map.get(hit.node_id)
            if node is not None:
                results.append((node, hit.score))
        return self._dedupe_ranked_nodes(results)

    async def semantic_search_with_graph_expansion(
        self,
        query: str,
        top_k: int = 10,
        threshold: float = 0.3,
        depth: int = 2,
    ) -> list[tuple[MemoryNode, float]]:
        """
        Two-phase retrieval:
        1. Semantic search → seed nodes
        2. BFS graph expansion → context nodes
        
        Returns union, prioritised by: vector score > graph proximity
        """
        seed_results = await self.semantic_search(query, top_k=top_k, threshold=threshold)
        seen_ids: set[str] = {n.id for n, _ in seed_results}
        expanded: list[tuple[MemoryNode, float]] = list(seed_results)

        if seed_results and depth > 0:
            neighbour_map = await self._storage.get_neighbours_for_nodes(
                [seed_node.id for seed_node, _ in seed_results],
                self.collection,
                direction="both",
                max_depth=depth,
            )
            for seed_node, seed_score in seed_results:
                for nbr in neighbour_map.get(seed_node.id, []):
                    if nbr.id not in seen_ids:
                        seen_ids.add(nbr.id)
                        # Discount the neighbour score by depth penalty
                        expanded.append((nbr, seed_score * 0.6))

        # Sort by score descending
        expanded.sort(key=lambda x: x[1], reverse=True)
        return self._dedupe_ranked_nodes(expanded)

    # ------------------------------------------------------------------ #
    # Cluster Operations                                                   #
    # ------------------------------------------------------------------ #

    async def add_cluster(
        self,
        name: str,
        cluster_type: ClusterType = ClusterType.SEMANTIC,
        node_ids: Optional[list[str]] = None,
    ) -> MemoryCluster:
        cluster = MemoryCluster(
            collection=self.collection,
            name=name,
            cluster_type=cluster_type,
            node_ids=node_ids or [],
        )
        await self._storage.upsert_cluster(cluster)
        return cluster

    async def get_cluster(self, cluster_id: str) -> Optional[MemoryCluster]:
        return await self._storage.get_cluster(cluster_id, self.collection)

    async def update_cluster(self, cluster: MemoryCluster) -> None:
        cluster.updated_at = time.time()
        await self._storage.upsert_cluster(cluster)

    async def list_clusters(self) -> list[MemoryCluster]:
        return await self._storage.list_clusters(self.collection)

    async def delete_cluster(self, cluster_id: str) -> bool:
        return await self._storage.delete_cluster(cluster_id, self.collection)

    # ------------------------------------------------------------------ #
    # Bulk / utility                                                       #
    # ------------------------------------------------------------------ #

    async def bulk_add_nodes(
        self,
        items: list[dict],
    ) -> list[MemoryNode]:
        """
        Efficiently add many nodes at once.
        items: list of dicts matching add_node() kwargs.
        """
        contents = [item["content"] for item in items]
        embeddings = await self._embedding_client.embed_batch(contents)

        nodes = []
        for item, embedding in zip(items, embeddings):
            node = MemoryNode(
                id=item.get("node_id") or item.get("id") or MemoryNode.model_fields["id"].default_factory(),
                collection=self.collection,
                content=item["content"],
                node_type=NodeType(item.get("node_type", "fact")),
                tier=MemoryTier(item.get("tier", "episodic")),
                importance=item.get("importance", 0.5),
                source=item.get("source"),
                source_agent_id=item.get("source_agent_id"),
                tags=item.get("tags", []),
                metadata=item.get("metadata", {}),
                pinned=item.get("pinned", False),
            )
            node.set_embedding(embedding)
            await self._storage.upsert_node(node)
            await self._vector_store.upsert(
                collection=self.collection,
                node_id=node.id,
                embedding=embedding,
                content=node.content,
            )
            nodes.append(node)
        return nodes

    async def get_stats(self) -> dict:
        """Return high-level graph statistics."""
        total = await self._storage.count_nodes(self.collection)
        clusters = await self._storage.list_clusters(self.collection)

        # Breakdown by tier and type
        all_nodes = await self._storage.list_nodes(self.collection, limit=100_000)
        nodes_by_tier: dict[str, int] = {}
        nodes_by_type: dict[str, int] = {}
        for n in all_nodes:
            tier_key = n.tier.value if hasattr(n.tier, "value") else str(n.tier)
            type_key = n.node_type.value if hasattr(n.node_type, "value") else str(n.node_type)
            nodes_by_tier[tier_key] = nodes_by_tier.get(tier_key, 0) + 1
            nodes_by_type[type_key] = nodes_by_type.get(type_key, 0) + 1

        # Count edges (sum outgoing edges for all nodes to avoid double-count)
        try:
            total_edges = await self._storage.count_edges(self.collection)
        except (AttributeError, NotImplementedError):
            # Fallback: count via list_nodes + get_edges
            total_edges = 0
            seen_edge_ids: set[str] = set()
            for n in all_nodes:
                edges = await self._storage.get_edges_for_node(n.id, self.collection, direction="out")
                for e in edges:
                    if e.id not in seen_edge_ids:
                        seen_edge_ids.add(e.id)
                        total_edges += 1

        return {
            "collection": self.collection,
            "total_nodes": total,
            "total_edges": total_edges,
            "total_clusters": len(clusters),
            "nodes_by_tier": nodes_by_tier,
            "nodes_by_type": nodes_by_type,
            "cluster_summary": [
                {"name": c.name, "type": c.cluster_type.value, "size": c.size}
                for c in clusters
            ],
        }

    # ------------------------------------------------------------------ #
    # Dedup helpers                                                        #
    # ------------------------------------------------------------------ #

    def _dedupe_ranked_nodes(
        self,
        results: list[tuple[MemoryNode, float]],
    ) -> list[tuple[MemoryNode, float]]:
        deduped: dict[str, tuple[MemoryNode, float]] = {}
        for node, score in results:
            key = self._dedup_key_for_node(node)
            existing = deduped.get(key)
            if existing is None or self._rank_tuple(node, score) > self._rank_tuple(existing[0], existing[1]):
                deduped[key] = (node, score)

        final_results = list(deduped.values())
        final_results.sort(key=lambda item: self._rank_tuple(item[0], item[1]), reverse=True)
        return final_results

    def _dedup_key_for_node(self, node: MemoryNode) -> str:
        metadata = node.metadata or {}
        if metadata.get("question_key"):
            return f"question:{metadata['question_key']}"
        if metadata.get("chunk_hash"):
            return f"chunk:{metadata['chunk_hash']}"
        if metadata.get("content_hash"):
            return f"content:{metadata['content_hash']}"
        if metadata.get("merged_from"):
            merged = ",".join(sorted(str(value) for value in metadata["merged_from"]))
            return f"merged:{merged}"
        if metadata.get("lineage_summary_ids"):
            lineage = ",".join(sorted(str(value) for value in metadata["lineage_summary_ids"]))
            return f"lineage:{lineage}"
        return f"content:{self._hash_text(node.content)}"

    def _rank_tuple(self, node: MemoryNode, score: float) -> tuple[float, int, float, float]:
        tier_priority = {
            MemoryTier.WORKING: 5,
            MemoryTier.SEMANTIC: 4,
            MemoryTier.PROCEDURAL: 3,
            MemoryTier.EPISODIC: 2,
            MemoryTier.ARCHIVED: 1,
        }
        return (
            score,
            tier_priority.get(node.tier, 0),
            node.importance,
            node.last_accessed,
        )

    @staticmethod
    def _hash_text(text: str) -> str:
        normalized = re.sub(r"\s+", " ", text or "").strip().lower()
        return hashlib.sha1(normalized.encode("utf-8")).hexdigest()

"""
MemoryGraph — high-level graph operations over the storage + vector layers.

This is the unified API that the Memory Agent and Context Broker use.
It coordinates between the StorageBackend (graph topology) and the
VectorStore (semantic search), keeping them in sync.
"""
from __future__ import annotations

import hashlib
import heapq
import numpy as np
import re
import time
from typing import Optional, Union

from stixdb.graph.node import MemoryNode, NodeType, MemoryTier
from stixdb.graph.edge import RelationEdge, RelationType
from stixdb.graph.cluster import MemoryCluster, ClusterType
from stixdb.graph.summary_index import extract_summary_connection_entries
from stixdb.storage.base import StorageBackend
from stixdb.storage.embeddings import EmbeddingClient
from stixdb.storage.vector_store import MemoryVectorStore
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

        # Persistent vector stores only need a rebuild when they are missing
        # data. The in-memory vector backend is treated as a hot cache and
        # should not load the entire corpus into RAM.
        if isinstance(self._vector_store, MemoryVectorStore):
            working_nodes = await self._storage.list_nodes(
                self.collection,
                tier=MemoryTier.WORKING.value,
                limit=1000,
                offset=0,
                include_embedding=True,
            )
            await self._seed_vector_store(working_nodes, allow_embedding_generation=True)
            return

        try:
            storage_count = await self._storage.count_nodes(self.collection)
            vector_count = await self._vector_store.count(self.collection)
            if storage_count > 0 and vector_count >= storage_count:
                return
        except Exception:
            pass

        # Paginate initialization to avoid pinning too many pages in the database buffer pool.
        batch_size = 250
        offset = 0
        while True:
            existing_nodes = await self._storage.list_nodes(
                self.collection,
                limit=batch_size,
                offset=offset,
                include_embedding=True,
            )
            if not existing_nodes:
                break

            await self._seed_vector_store(existing_nodes, allow_embedding_generation=False)

            offset += len(existing_nodes)
            if len(existing_nodes) < batch_size:
                break

    async def _sync_vector_store(self, node: MemoryNode) -> None:
        """Keep the vector index aligned with the node's tier."""
        if isinstance(self._vector_store, MemoryVectorStore) and node.tier != MemoryTier.WORKING:
            await self._vector_store.delete(self.collection, node.id)
            return

        embedding = node.get_embedding_array()
        if embedding is None:
            try:
                embedding = await self._embedding_client.embed_text(node.content)
                node.set_embedding(embedding)
                await self._storage.upsert_node(node)
            except Exception as _emb_err:
                import structlog as _sl
                _sl.get_logger(__name__).warning(
                    "Embedding retry failed in _sync_vector_store — skipping vector index",
                    error=str(_emb_err),
                    collection=self.collection,
                )
                return  # node stored in graph; semantic search skips it until re-embedded

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
        parent_node_ids: Optional[list[str]] = None,
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
            parent_node_ids=parent_node_ids or [],
            pinned=pinned,
        )
        # Compute embedding — non-fatal; node is still stored for keyword search.
        try:
            embedding = await self._embedding_client.embed_text(content)
            node.set_embedding(embedding)
        except Exception as _emb_err:
            import structlog as _sl
            _sl.get_logger(__name__).warning(
                "Embedding failed — storing node without vector",
                error=str(_emb_err),
                collection=self.collection,
            )

        # Persist in graph and sync the hot vector cache when applicable.
        await self._storage.upsert_node(node)
        await self._sync_vector_store(node)
        return node

    async def get_node(self, node_id: str) -> Optional[MemoryNode]:
        return await self._storage.get_node(node_id, self.collection)

    async def get_nodes(self, node_ids: list[str]) -> list[MemoryNode]:
        if not node_ids:
            return []
        unique_ids = list(dict.fromkeys(node_ids))
        return await self._storage.get_nodes(unique_ids, self.collection)

    async def update_node(self, node: MemoryNode) -> None:
        """Persist changes to an existing MemoryNode. Re-embeds if content changed."""
        await self._storage.upsert_node(node)
        await self._sync_vector_store(node)

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
        include_embedding: bool = False,
    ) -> list[MemoryNode]:
        return await self._storage.list_nodes(
            self.collection,
            tier=tier,
            node_type=node_type,
            limit=limit,
            offset=offset,
            include_embedding=include_embedding,
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

    async def store_edge(self, edge: RelationEdge) -> RelationEdge:
        """Store a fully-constructed RelationEdge directly, preserving all fields
        (including provenance and rationale set by the AST extractor or Enricher)."""
        await self._storage.upsert_edge(edge)
        return edge

    async def list_edges(self) -> list[RelationEdge]:
        """Return all edges in this collection."""
        return await self._storage.list_edges(self.collection)

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
        hits = await self.semantic_search_hits(
            query=query,
            top_k=top_k,
            threshold=threshold,
        )
        nodes = await self.get_nodes([hit.node_id for hit in hits])
        node_map = {node.id: node for node in nodes}
        results = []
        for hit in hits:
            node = node_map.get(hit.node_id)
            if node is not None:
                results.append((node, hit.score))
        return self._dedupe_ranked_nodes(results)

    async def semantic_search_hits(
        self,
        query: str,
        top_k: int = 10,
        threshold: float = 0.3,
    ) -> list[VectorSearchResult]:
        """Return vector hits without hydrating full nodes from storage."""
        try:
            query_embedding = await self._embedding_client.embed_text(query)
        except Exception as _emb_err:
            import structlog as _sl
            _sl.get_logger(__name__).warning(
                "Query embedding failed — semantic search returning empty",
                error=str(_emb_err),
                collection=self.collection,
            )
            return []
        return await self.semantic_search_hits_from_embedding(
            query_embedding=query_embedding,
            query=query,
            top_k=top_k,
            threshold=threshold,
        )

    async def semantic_search_hits_from_embedding(
        self,
        query_embedding: np.ndarray,
        query: str = "",
        top_k: int = 10,
        threshold: float = 0.3,
    ) -> list[VectorSearchResult]:
        """Search the vector index using a precomputed query embedding."""
        return await self._vector_store.search(
            collection=self.collection,
            query_embedding=query_embedding,
            top_k=top_k,
            threshold=threshold,
        )

    async def _seed_vector_store(
        self,
        nodes: list[MemoryNode],
        allow_embedding_generation: bool = True,
    ) -> None:
        for node in nodes:
            embedding = node.get_embedding_array()
            if embedding is None:
                if not allow_embedding_generation:
                    continue
                try:
                    embedding = await self._embedding_client.embed_text(node.content)
                    node.set_embedding(embedding)
                    await self._storage.upsert_node(node)
                except Exception as _emb_err:
                    import structlog as _sl
                    _sl.get_logger(__name__).warning(
                        "Embedding failed during seed — skipping node vector",
                        error=str(_emb_err),
                        collection=self.collection,
                    )
                    continue
            await self._vector_store.upsert(
                collection=self.collection,
                node_id=node.id,
                embedding=embedding,
                content=node.content,
            )

    async def _semantic_search_streaming(
        self,
        query: str,
        query_embedding,
        top_k: int,
        threshold: float,
    ) -> list[tuple[MemoryNode, float]]:
        batch_size = 1000
        offset = 0
        best: list[tuple[float, int, MemoryNode]] = []
        missing_candidates: list[tuple[float, int, MemoryNode]] = []
        seq = 0
        query_terms = self._query_terms(query)
        missing_candidate_limit = max(top_k * 4, 64)

        while True:
            batch = await self._storage.list_nodes(
                self.collection,
                limit=batch_size,
                offset=offset,
                include_embedding=True,
            )
            if not batch:
                break

            valid_nodes: list[MemoryNode] = []
            valid_embeddings = []
            for node in batch:
                embedding = node.get_embedding_array()
                if embedding is None:
                    lexical_score = self._lexical_candidate_score(node.content, query_terms)
                    if lexical_score > 0.0:
                        item = (lexical_score, seq, node)
                        if len(missing_candidates) < missing_candidate_limit:
                            heapq.heappush(missing_candidates, item)
                        elif lexical_score > missing_candidates[0][0]:
                            heapq.heapreplace(missing_candidates, item)
                        seq += 1
                    continue
                valid_nodes.append(node)
                valid_embeddings.append(embedding)

            if valid_embeddings:
                matrix = np.stack(valid_embeddings)
                scores = matrix @ query_embedding
                for node, score in zip(valid_nodes, scores):
                    score_value = float(score)
                    if score_value < threshold:
                        continue
                    item = (score_value, seq, node)
                    if len(best) < top_k:
                        heapq.heappush(best, item)
                    elif score_value > best[0][0]:
                        heapq.heapreplace(best, item)
                    seq += 1

            offset += len(batch)
            if len(batch) < batch_size:
                break

        if missing_candidates:
            shortlisted_nodes = [node for _, _, node in sorted(missing_candidates, reverse=True)]
            missing_embeddings = await self._embedding_client.embed_batch(
                [node.content for node in shortlisted_nodes]
            )
            for node, embedding in zip(shortlisted_nodes, missing_embeddings):
                score_value = float(embedding @ query_embedding)
                if score_value < threshold:
                    continue
                item = (score_value, seq, node)
                if len(best) < top_k:
                    heapq.heappush(best, item)
                elif score_value > best[0][0]:
                    heapq.heapreplace(best, item)
                seq += 1

        best.sort(key=lambda item: item[0], reverse=True)
        return [(node, score) for score, _, node in best]

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
        2. Summary metadata expansion → direct related nodes
        3. BFS graph expansion → fallback context nodes

        Returns union, prioritised by: vector score > graph proximity
        """
        seed_results = await self.semantic_search(query, top_k=top_k, threshold=threshold)
        return await self._expand_from_seeds(seed_results, top_k=top_k, depth=depth)

    async def keyword_search_with_graph_expansion(
        self,
        query: str,
        top_k: int = 10,
        threshold: float = 0.1,
        depth: int = 2,
    ) -> list[tuple[MemoryNode, float]]:
        """
        Keyword-based retrieval — no embedding API call.

        1. Extract query tokens (3+ char words)
        2. Score nodes by tag overlap (2× weight) + content term overlap
        3. Take top-k seeds above threshold
        4. Graph expansion from seeds (identical BFS to semantic path)

        Scans working and semantic tiers first; falls through to episodic
        if not enough seeds are found.
        """
        query_tokens = self._query_terms(query)
        if not query_tokens:
            return []

        # Prioritise hot tiers — bounded scan, no embedding needed
        nodes = await self.list_nodes(tier="working", limit=4096, include_embedding=False)
        nodes += await self.list_nodes(tier="semantic", limit=2000, include_embedding=False)

        scored = [(n, self._keyword_score(n, query_tokens)) for n in nodes]
        seeds = [(n, s) for n, s in scored if s >= threshold]

        if len(seeds) < top_k:
            ep_nodes = await self.list_nodes(tier="episodic", limit=3000, include_embedding=False)
            seen = {n.id for n, _ in seeds}
            for node in ep_nodes:
                if node.id in seen:
                    continue
                score = self._keyword_score(node, query_tokens)
                if score >= threshold:
                    seeds.append((node, score))

        seeds.sort(key=lambda x: x[1], reverse=True)
        seed_results = seeds[:top_k]
        return await self._expand_from_seeds(seed_results, top_k=top_k, depth=depth)

    async def hybrid_search_with_graph_expansion(
        self,
        query: str,
        top_k: int = 10,
        threshold: float = 0.1,
        depth: int = 2,
        semantic_weight: float = 0.7,
    ) -> list[tuple[MemoryNode, float]]:
        """
        Hybrid retrieval: keyword scoring + semantic vector search, scores merged.

        combined = semantic_weight * semantic_score + (1 - semantic_weight) * keyword_score

        Nodes appearing in only one pass still contribute via their single score.
        No API call cost beyond what semantic_search already requires.
        """
        # ── keyword pass (no embedding API call) ─────────────────────────
        query_tokens = self._query_terms(query)
        keyword_scores: dict[str, tuple[MemoryNode, float]] = {}
        if query_tokens:
            kw_nodes = await self.list_nodes(tier="working", limit=4096, include_embedding=False)
            kw_nodes += await self.list_nodes(tier="semantic", limit=2000, include_embedding=False)
            seen_kw = {n.id for n in kw_nodes}
            ep_nodes = await self.list_nodes(tier="episodic", limit=3000, include_embedding=False)
            kw_nodes += [n for n in ep_nodes if n.id not in seen_kw]
            for node in kw_nodes:
                score = self._keyword_score(node, query_tokens)
                if score > 0.0:
                    keyword_scores[node.id] = (node, score)

        # ── semantic pass (vector embedding + cosine similarity) ──────────
        sem_results = await self.semantic_search(query, top_k=top_k * 3, threshold=0.0)
        semantic_scores: dict[str, tuple[MemoryNode, float]] = {
            node.id: (node, score) for node, score in sem_results
        }

        # ── merge ─────────────────────────────────────────────────────────
        all_ids = set(keyword_scores) | set(semantic_scores)
        merged: list[tuple[MemoryNode, float]] = []
        for nid in all_ids:
            node = (semantic_scores.get(nid) or keyword_scores[nid])[0]
            k_score = keyword_scores[nid][1] if nid in keyword_scores else 0.0
            s_score = semantic_scores[nid][1] if nid in semantic_scores else 0.0
            combined = semantic_weight * s_score + (1.0 - semantic_weight) * k_score
            if combined >= threshold:
                merged.append((node, combined))

        merged.sort(key=lambda x: x[1], reverse=True)
        return await self._expand_from_seeds(merged[:top_k], top_k=top_k, depth=depth)

    async def _expand_from_seeds(
        self,
        seed_results: list[tuple[MemoryNode, float]],
        top_k: int = 10,
        depth: int = 2,
    ) -> list[tuple[MemoryNode, float]]:
        """
        Graph expansion from a list of (node, score) seed pairs.
        Shared by both semantic and keyword retrieval paths.
        """
        seen_ids: set[str] = {n.id for n, _ in seed_results}
        expanded: list[tuple[MemoryNode, float]] = list(seed_results)

        if not seed_results or depth <= 0:
            return self._dedupe_ranked_nodes(expanded)

        expansion_seeds = seed_results[: min(len(seed_results), max(4, top_k // 3))]
        seed_score_map = {seed_node.id: seed_score for seed_node, seed_score in expansion_seeds}

        summary_related_ids: list[str] = []
        summary_related_scores: dict[str, float] = {}
        summary_seed_related_ids: dict[str, list[str]] = {}
        fallback_bfs_seed_ids: list[str] = []

        for seed_node, seed_score in expansion_seeds:
            if seed_node.node_type == NodeType.SUMMARY:
                entries = extract_summary_connection_entries(seed_node.metadata or {})
                if entries:
                    max_related = max(4, min(24, top_k * max(1, depth)))
                    related_ids: list[str] = []
                    for entry in entries[:max_related]:
                        node_id = str(entry.get("node_id") or "").strip()
                        if not node_id or node_id == seed_node.id:
                            continue
                        related_ids.append(node_id)
                        weight = max(0.1, float(entry.get("weight", 1.0) or 1.0))
                        rank = max(1, int(entry.get("rank", 1) or 1))
                        score = seed_score * 0.9 * weight / rank
                        summary_related_scores[node_id] = max(
                            summary_related_scores.get(node_id, 0.0),
                            score,
                        )
                    if related_ids:
                        summary_seed_related_ids[seed_node.id] = related_ids
                        summary_related_ids.extend(related_ids)
                        continue
            fallback_bfs_seed_ids.append(seed_node.id)

        if summary_related_ids:
            related_nodes = await self.get_nodes(list(dict.fromkeys(summary_related_ids)))
            returned_ids = {node.id for node in related_nodes}
            for node in related_nodes:
                if node.id in seen_ids:
                    continue
                seen_ids.add(node.id)
                expanded.append((node, summary_related_scores.get(node.id, 0.0)))

            for seed_id, related_ids in summary_seed_related_ids.items():
                if not any(node_id in returned_ids for node_id in related_ids):
                    fallback_bfs_seed_ids.append(seed_id)

        fallback_bfs_seed_ids = list(dict.fromkeys(fallback_bfs_seed_ids))
        if fallback_bfs_seed_ids:
            neighbour_map = await self._storage.get_neighbours_for_nodes(
                fallback_bfs_seed_ids,
                self.collection,
                direction="both",
                max_depth=depth,
            )
            for seed_id in fallback_bfs_seed_ids:
                seed_score = seed_score_map.get(seed_id, 0.0)
                for nbr in neighbour_map.get(seed_id, []):
                    if nbr.id not in seen_ids:
                        seen_ids.add(nbr.id)
                        expanded.append((nbr, seed_score * 0.6))

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
        try:
            embeddings = await self._embedding_client.embed_batch(contents)
        except Exception as _emb_err:
            import structlog as _sl
            _sl.get_logger(__name__).warning(
                "Batch embedding failed — storing nodes without vectors",
                error=str(_emb_err),
                count=len(contents),
                collection=self.collection,
            )
            embeddings = [None] * len(contents)

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
                parent_node_ids=item.get("parent_node_ids", []),
                pinned=item.get("pinned", False),
            )
            if embedding is not None:
                node.set_embedding(embedding)
            await self._storage.upsert_node(node)
            await self._sync_vector_store(node)
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

    @staticmethod
    def _query_terms(query: str) -> set[str]:
        return {term for term in re.findall(r"[a-zA-Z0-9_]+", query.lower()) if len(term) >= 3}

    @staticmethod
    def _keyword_score(node: MemoryNode, query_tokens: set[str]) -> float:
        """Score a node by keyword overlap. Tag matches are weighted 2× over content matches."""
        if not query_tokens:
            return 0.0
        n = len(query_tokens)
        node_tags_lower = {t.lower() for t in (node.tags or [])}
        tag_hits = sum(1 for t in query_tokens if t in node_tags_lower)
        content_lower = (node.content or "").lower()
        content_hits = sum(1 for t in query_tokens if t in content_lower)
        return min(1.0, (tag_hits * 2.0 + content_hits) / n)

    @staticmethod
    def _lexical_candidate_score(content: str, query_terms: set[str]) -> float:
        if not query_terms or not content:
            return 0.0
        lowered = content.lower()
        hits = sum(1 for term in query_terms if term in lowered)
        if hits == 0:
            return 0.0
        return hits / max(1, len(query_terms))

    @staticmethod
    def _best_hit_lexical_overlap(hits: list[VectorSearchResult], query_terms: set[str]) -> int:
        best = 0
        for hit in hits:
            content = getattr(hit, "content", "") or ""
            if not content:
                continue
            lowered = content.lower()
            overlap = sum(1 for term in query_terms if term in lowered)
            if overlap > best:
                best = overlap
                if best == len(query_terms):
                    break
        return best

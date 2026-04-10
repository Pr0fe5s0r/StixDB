
"""
Consolidator — autonomous memory consolidation and pruning.

The Consolidator is the "memory housekeeping" module. It:
1. Detects semantically similar nodes and merges them into a SUMMARY node
2. Prunes highly decayed nodes (below the importance threshold)
3. Creates lineage edges (DERIVED_FROM, SUMMARIZES) to preserve provenance
4. Updates cluster memberships after merge operations

The Consolidator emits "thinking traces" — structured logs of every
decision it makes, so engineers can understand why memory was reorganised.
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Awaitable, Callable, Optional

import numpy as np

from stixdb.graph.node import MemoryNode, NodeType, MemoryTier
from stixdb.graph.edge import RelationEdge, RelationType
from stixdb.graph.cluster import MemoryCluster, ClusterType
from stixdb.graph.memory_graph import MemoryGraph
from stixdb.graph.summary_index import (
    build_connection_entries,
    build_summary_connection_index,
    merge_summary_connection_index,
)
from stixdb.config import AgentConfig
from stixdb.observability.tracer import get_tracer


class ConsolidationResult:
    """Result report from a single consolidation cycle."""
    def __init__(self) -> None:
        self.merged_pairs: list[tuple[str, str, str]] = []   # (src_id, tgt_id, summary_id)
        self.synthesized_summaries: list[str] = []           # summary node IDs created by synthesis zone
        self.pruned_node_ids: list[str] = []
        self.new_clusters: list[str] = []
        self.thoughts: list[str] = []    # Human-readable agent reasoning

    def to_dict(self) -> dict:
        return {
            "merged_count": len(self.merged_pairs),
            "synthesized_count": len(self.synthesized_summaries),
            "pruned_count": len(self.pruned_node_ids),
            "new_clusters": len(self.new_clusters),
            "thoughts": self.thoughts,
        }


class Consolidator:
    """
    Autonomous memory consolidation engine.
    
    Runs in the Memory Agent's background cycle to keep the graph
    compact, coherent, and high-quality.
    """

    def __init__(
        self,
        graph: MemoryGraph,
        config: AgentConfig,
        synthesize_fn: Optional[Callable[[list], Awaitable[str]]] = None,
    ) -> None:
        self.graph = graph
        self.config = config
        self._synthesize_fn = synthesize_fn   # optional LLM synthesis hook
        self._cycle = 0                        # rotation counter for exploration
        self._tracer = get_tracer()

    async def run_cycle(self) -> ConsolidationResult:
        """
        Run one full consolidation cycle:
        1.  Merge candidates (sim >= consolidation_threshold) — deduplicate, archive originals
        1b. Synthesize candidates (synthesis_lower <= sim < threshold) — build abstractions, KEEP originals
        1c. Remove exact duplicates
        2.  Prune dead nodes
        3.  Rebuild clusters
        """
        result = ConsolidationResult()

        # Phase 1: Merge (deduplication — high similarity, archive originals)
        await self._find_and_merge(result)

        # Phase 1b: Synthesize (abstraction — medium similarity, originals kept)
        await self._synthesize_zone(result)

        # Phase 1c: Remove exact duplicates
        await self._prune_exact_duplicates(result)

        # Phase 2: Prune dead nodes
        await self._prune_dead_nodes(result)

        # Phase 3: Update clusters
        await self._rebuild_clusters(result)

        # Advance exploration cursor so the next cycle samples a different slice
        self._cycle += 1

        # Emit consolidated trace
        self._tracer.record_consolidation(
            collection=self.graph.collection,
            merged=len(result.merged_pairs),
            pruned=len(result.pruned_node_ids),
            thoughts=result.thoughts,
        )

        return result

    # ------------------------------------------------------------------ #
    # Phase 1: Merge                                                        #
    # ------------------------------------------------------------------ #

    async def _find_and_merge(self, result: ConsolidationResult) -> None:
        """
        Identify semantically similar nodes and merge them into summaries.

        Improvements over the naive approach:
        - Rotating offset sampling ensures every cycle explores a DIFFERENT
          slice of the collection, so all nodes get explored over time.
        - Multi-tier sampling includes working-tier (hot/recent) nodes
          alongside semantic and episodic nodes.
        - Union-Find clustering groups ALL mutually similar nodes in the
          batch into one summary per cluster — not just pairwise merges.
        - Optional LLM synthesis generates meaningful summary text instead
          of a raw concatenation.
        """
        threshold = self.config.consolidation_similarity_threshold

        # ── 1. Sample a rotating, multi-tier batch ──────────────────────
        candidates = await self._sample_candidates()
        embedded = [
            (n, np.array(n.embedding, dtype=np.float32))
            for n in candidates
            if n.embedding is not None and not n.pinned
        ]
        if len(embedded) < 2:
            return

        # ── 2. Build similarity adjacency (pairwise upper-triangle) ─────
        adj: dict[str, set[str]] = defaultdict(set)
        best_sim: dict[str, float] = {}  # node_id → max similarity seen

        for i in range(len(embedded)):
            node_a, emb_a = embedded[i]
            for j in range(i + 1, len(embedded)):
                node_b, emb_b = embedded[j]
                sim = float(np.clip(np.dot(emb_a, emb_b), -1.0, 1.0))
                if sim >= threshold:
                    adj[node_a.id].add(node_b.id)
                    adj[node_b.id].add(node_a.id)
                    best_sim[node_a.id] = max(best_sim.get(node_a.id, 0.0), sim)
                    best_sim[node_b.id] = max(best_sim.get(node_b.id, 0.0), sim)

        if not adj:
            return

        # ── 3. Find connected clusters via BFS ───────────────────────────
        id_to_item = {n.id: (n, emb) for n, emb in embedded}
        clusters = self._find_clusters(embedded, adj)

        # ── 4. Merge each cluster ────────────────────────────────────────
        merged_ids: set[str] = set()
        for cluster in clusters:
            # Skip if any member was already merged this cycle
            if any(n.id in merged_ids for n, _ in cluster):
                continue

            avg_sim = float(np.mean([best_sim.get(n.id, threshold) for n, _ in cluster]))

            # If an existing SUMMARY is in the cluster, absorb the rest into it
            summary_nodes = [n for n, _ in cluster if n.node_type == NodeType.SUMMARY and not n.pinned]
            if summary_nodes:
                anchor = summary_nodes[0]
                anchor_emb = id_to_item[anchor.id][1]
                others = [(n, emb) for n, emb in cluster if n.id != anchor.id]
                for other_node, _ in others:
                    await self._absorb_into_summary(anchor, anchor_emb, other_node, avg_sim)
                    merged_ids.add(other_node.id)
                    # Re-compute anchor embedding for next absorption
                    anchor_emb = np.array(anchor.embedding, dtype=np.float32)
                merged_ids.add(anchor.id)
                ids = [n.id[:8] for n, _ in cluster]
                result.merged_pairs.append((anchor.id, others[0][0].id if others else anchor.id, anchor.id))
                result.thoughts.append(
                    f"Absorbed {len(others)} node(s) into summary {anchor.id[:8]} "
                    f"(cluster size={len(cluster)}, avg_sim={avg_sim:.3f}). "
                    f"Members: {', '.join(ids)}"
                )
            else:
                # All new nodes — create one summary for the whole cluster
                summary_id = await self._merge_cluster(cluster, avg_sim)
                for n, _ in cluster:
                    merged_ids.add(n.id)
                ids = [n.id[:8] for n, _ in cluster]
                result.merged_pairs.append((cluster[0][0].id, cluster[1][0].id, summary_id))
                result.thoughts.append(
                    f"Merged cluster of {len(cluster)} nodes into summary {summary_id[:8]} "
                    f"(avg_sim={avg_sim:.3f}, threshold={threshold:.3f}). "
                    f"Members: {', '.join(ids)}"
                )

    # ── Exploration helpers ────────────────────────────────────────────────

    async def _sample_candidates(self) -> list:
        """
        Sample a rotating, importance-weighted batch from all active tiers.

        The rotation offset advances by (batch // 3) each cycle so that:
          - Cycle 0 sees nodes 0..N
          - Cycle 1 sees nodes N..2N
          - Cycle K wraps back around
        Working-tier nodes are always included (they're hot/recent).
        """
        batch = self.config.max_consolidation_batch
        per_tier = max(4, batch // 3)
        offset = (self._cycle * per_tier) % max(1, per_tier * 10)

        # Hot nodes always included — they're recently accessed and likely co-relevant
        working  = await self.graph.list_nodes(tier="working",  limit=per_tier,     offset=0)
        semantic = await self.graph.list_nodes(tier="semantic", limit=per_tier,     offset=offset)
        episodic = await self.graph.list_nodes(tier="episodic", limit=per_tier * 2, offset=offset)

        seen: set[str] = set()
        merged: list = []
        for node in working + semantic + episodic:
            if node.id not in seen:
                seen.add(node.id)
                merged.append(node)

        # Bias toward high-importance nodes within the batch
        merged.sort(key=lambda n: n.importance, reverse=True)
        return merged[:batch]

    @staticmethod
    def _find_clusters(
        embedded: list,
        adj: dict[str, set[str]],
    ) -> list[list]:
        """
        Group similar nodes into connected clusters (BFS on the adjacency graph).
        Returns only clusters with >= 2 members.
        """
        visited: set[str] = set()
        clusters: list[list] = []
        id_to_item = {n.id: (n, emb) for n, emb in embedded}

        for node, _ in embedded:
            if node.id in visited or node.id not in adj:
                continue
            # BFS
            cluster_ids: list[str] = []
            queue = [node.id]
            while queue:
                nid = queue.pop()
                if nid in visited:
                    continue
                visited.add(nid)
                cluster_ids.append(nid)
                for neighbor in adj.get(nid, set()):
                    if neighbor not in visited:
                        queue.append(neighbor)
            if len(cluster_ids) >= 2:
                clusters.append([id_to_item[nid] for nid in cluster_ids if nid in id_to_item])

        return clusters

    async def _merge_cluster(self, cluster: list, avg_similarity: float) -> str:
        """
        Create one SUMMARY node from an entire cluster of similar nodes.
        Uses LLM synthesis when available, concatenation otherwise.
        """
        nodes = [n for n, _ in cluster]

        def lineage_entry(node) -> dict:
            meta = node.metadata or {}
            return {
                "node_id": node.id,
                "source": node.source,
                "filepath": meta.get("filepath"),
                "char_start": meta.get("char_start"),
                "char_end": meta.get("char_end"),
                "created_at": node.created_at,
            }

        combined_content = await self._build_summary_content(nodes)

        # Centroid embedding across all members
        embs = [np.array(n.embedding, dtype=np.float32) for n in nodes if n.embedding]
        avg_emb = np.mean(embs, axis=0).astype(np.float32) if embs else None
        if avg_emb is not None:
            norm = np.linalg.norm(avg_emb)
            if norm > 0:
                avg_emb = avg_emb / norm

        combined_importance = max(n.importance for n in nodes) * 0.95

        summary_node = MemoryNode(
            collection=self.graph.collection,
            content=combined_content,
            node_type=NodeType.SUMMARY,
            tier=MemoryTier.SEMANTIC,
            importance=combined_importance,
            parent_node_ids=[n.id for n in nodes],
            source="agent-consolidator",
            metadata={
                "merged_from": [n.id for n in nodes],
                "cluster_size": len(nodes),
                "avg_similarity": avg_similarity,
                "merged_at": time.time(),
                "source_lineage": [lineage_entry(n) for n in nodes],
                "llm_synthesized": self._synthesize_fn is not None,
                "connection_index": build_summary_connection_index(
                    summary_id=None,
                    summary_kind="cluster_merge",
                    source="agent-consolidator",
                    content_hash=self.graph._hash_text(combined_content),
                    entries=build_connection_entries(
                        [n.id for n in nodes],
                        relation_type=RelationType.DERIVED_FROM,
                        role="source",
                        weight=max(0.5, avg_similarity),
                        source="agent-consolidator",
                    ),
                ),
            },
        )
        summary_node.metadata["connection_index"] = build_summary_connection_index(
            summary_id=summary_node.id,
            summary_kind="cluster_merge",
            source="agent-consolidator",
            content_hash=self.graph._hash_text(combined_content),
            entries=summary_node.metadata["connection_index"]["entries"],
        )
        if avg_emb is not None:
            summary_node.set_embedding(avg_emb)

        await self.graph._storage.upsert_node(summary_node)
        if avg_emb is not None:
            await self.graph._vector_store.upsert(
                collection=self.graph.collection,
                node_id=summary_node.id,
                embedding=avg_emb,
                content=summary_node.content,
            )

        # Archive all source nodes and create lineage edges
        for node in nodes:
            node.tier = MemoryTier.ARCHIVED
            node.importance *= 0.5
            if self.config.lineage_safe_mode:
                node.pinned = True
                node.metadata = node.metadata or {}
                node.metadata["lineage_preserved"] = True
                node.metadata["lineage_summary_ids"] = sorted(
                    set(node.metadata.get("lineage_summary_ids", [])) | {summary_node.id}
                )
            await self.graph.update_node(node)
            await self.graph.add_edge(
                summary_node.id, node.id,
                relation_type=RelationType.DERIVED_FROM,
                weight=avg_similarity,
                created_by="agent",
            )

        return summary_node.id

    async def _build_summary_content(self, nodes: list) -> str:
        """
        Build summary text for a cluster of nodes.
        Uses LLM synthesis when a synthesize_fn is wired up; falls back
        to structured concatenation otherwise.
        """
        if self._synthesize_fn is not None:
            try:
                result = await self._synthesize_fn(nodes)
                if result and result.strip():
                    return result.strip()
            except Exception:
                pass  # fall through to concatenation

        # Concatenation fallback — more structured than a bare join
        parts = [n.content.strip() for n in nodes]
        return "[SUMMARY] " + " | ".join(parts)

    async def _merge_nodes(self, node_a: MemoryNode, node_b: MemoryNode, similarity: float) -> str:
        """
        Create a SUMMARY node from two similar nodes.
        The original nodes are kept but demoted to ARCHIVED tier.
        Lineage is preserved via DERIVED_FROM edges.
        """
        def lineage_entry(node: MemoryNode) -> dict:
            metadata = node.metadata or {}
            return {
                "node_id": node.id,
                "source": node.source,
                "filepath": metadata.get("filepath"),
                "page_number": metadata.get("page_number"),
                "page_start": metadata.get("page_start"),
                "page_end": metadata.get("page_end"),
                "char_start": metadata.get("char_start"),
                "char_end": metadata.get("char_end"),
                "created_at": node.created_at,
                "last_accessed": node.last_accessed,
            }

        # Build a combined summary (simple concatenation — LLM summary is optional)
        combined_content = (
            f"[SUMMARY] {node_a.content.strip()} | {node_b.content.strip()}"
        )
        # Average the embeddings as the centroid
        emb_a = np.array(node_a.embedding)
        emb_b = np.array(node_b.embedding)
        avg_emb = ((emb_a + emb_b) / 2.0).astype(np.float32)
        # Renormalise
        norm = np.linalg.norm(avg_emb)
        if norm > 0:
            avg_emb = avg_emb / norm

        # Inherit importance as max of the two
        combined_importance = max(node_a.importance, node_b.importance) * 0.95

        summary_node = MemoryNode(
            collection=self.graph.collection,
            content=combined_content,
            node_type=NodeType.SUMMARY,
            tier=MemoryTier.SEMANTIC,
            importance=combined_importance,
            parent_node_ids=[node_a.id, node_b.id],
            source="agent-consolidator",
            metadata={
                "merged_from": [node_a.id, node_b.id],
                "similarity": similarity,
                "merged_at": time.time(),
                "source_lineage": [lineage_entry(node_a), lineage_entry(node_b)],
                "connection_index": build_summary_connection_index(
                    summary_id=None,
                    summary_kind="pair_merge",
                    source="agent-consolidator",
                    content_hash=self.graph._hash_text(combined_content),
                    entries=build_connection_entries(
                        [node_a.id, node_b.id],
                        relation_type=RelationType.DERIVED_FROM,
                        role="source",
                        weight=similarity,
                        source="agent-consolidator",
                    ),
                ),
            },
        )
        summary_node.metadata["connection_index"] = build_summary_connection_index(
            summary_id=summary_node.id,
            summary_kind="pair_merge",
            source="agent-consolidator",
            content_hash=self.graph._hash_text(combined_content),
            entries=summary_node.metadata["connection_index"]["entries"],
        )
        summary_node.set_embedding(avg_emb)

        # Persist summary
        await self.graph._storage.upsert_node(summary_node)
        await self.graph._vector_store.upsert(
            collection=self.graph.collection,
            node_id=summary_node.id,
            embedding=avg_emb,
            content=summary_node.content,
        )

        # Archive originals
        node_a.tier = MemoryTier.ARCHIVED
        node_a.importance *= 0.5
        if self.config.lineage_safe_mode:
            node_a.pinned = True
            node_a.metadata["lineage_preserved"] = True
            node_a.metadata["lineage_summary_ids"] = sorted(
                set(node_a.metadata.get("lineage_summary_ids", [])) | {summary_node.id}
            )
        node_b.tier = MemoryTier.ARCHIVED
        node_b.importance *= 0.5
        if self.config.lineage_safe_mode:
            node_b.pinned = True
            node_b.metadata["lineage_preserved"] = True
            node_b.metadata["lineage_summary_ids"] = sorted(
                set(node_b.metadata.get("lineage_summary_ids", [])) | {summary_node.id}
            )
        await self.graph.update_node(node_a)
        await self.graph.update_node(node_b)

        # Create lineage edges
        await self.graph.add_edge(
            summary_node.id, node_a.id,
            relation_type=RelationType.DERIVED_FROM,
            weight=similarity,
            created_by="agent",
        )
        await self.graph.add_edge(
            summary_node.id, node_b.id,
            relation_type=RelationType.DERIVED_FROM,
            weight=similarity,
            created_by="agent",
        )

        return summary_node.id

    async def _absorb_into_summary(
        self,
        summary: MemoryNode,
        summary_emb: np.ndarray,
        other: MemoryNode,
        similarity: float,
    ) -> None:
        """
        Absorb a semantically similar node into an existing SUMMARY node.

        Instead of creating yet another summary (which would fragment the graph),
        we:
          1. Update the summary's embedding to the normalised centroid of both.
          2. Append the absorbed node's content to the summary text.
          3. Add a DERIVED_FROM edge (summary → absorbed node) for provenance.
          4. Archive the absorbed node so the consolidator won't revisit it.
        """
        other_emb = np.array(other.embedding, dtype=np.float32)
        summary.metadata = summary.metadata or {}
        new_emb = (summary_emb + other_emb) / 2.0
        norm = np.linalg.norm(new_emb)
        if norm > 0:
            new_emb = new_emb / norm
        summary.set_embedding(new_emb)

        # Extend summary content only if the absorbed text is not already present
        absorbed_snippet = other.content.strip()
        if absorbed_snippet not in summary.content:
            summary.content = f"{summary.content.rstrip()} | {absorbed_snippet}"

        # Track absorbed node in lineage metadata
        lineage = summary.metadata.get("source_lineage", [])
        lineage.append({
            "node_id": other.id,
            "source": other.source,
            "similarity": similarity,
            "absorbed_at": time.time(),
        })
        summary.metadata["source_lineage"] = lineage
        merged_from = list(summary.metadata.get("merged_from", []))
        if other.id not in merged_from:
            merged_from.append(other.id)
        summary.metadata["merged_from"] = merged_from
        summary.metadata["last_absorbed_at"] = time.time()
        summary.metadata["connection_index"] = merge_summary_connection_index(
            summary.metadata,
            summary_id=summary.id,
            summary_kind=str(summary.metadata.get("summary_kind") or "absorbed_summary"),
            source=summary.source or "agent-consolidator",
            content_hash=self.graph._hash_text(summary.content),
            entries=build_connection_entries(
                [other.id],
                relation_type=RelationType.DERIVED_FROM,
                role="absorbed",
                weight=similarity,
                source="agent-consolidator",
            ),
        )
        summary.parent_node_ids = sorted(set(summary.parent_node_ids) | {other.id})

        # Persist updated summary
        await self.graph._storage.upsert_node(summary)
        await self.graph._vector_store.upsert(
            collection=self.graph.collection,
            node_id=summary.id,
            embedding=new_emb,
            content=summary.content,
        )

        # Lineage edge: summary → absorbed node
        await self.graph.add_edge(
            summary.id, other.id,
            relation_type=RelationType.DERIVED_FROM,
            weight=similarity,
            created_by="agent",
        )

        # Archive the absorbed node
        other.tier = MemoryTier.ARCHIVED
        other.importance *= 0.5
        if self.config.lineage_safe_mode:
            other.pinned = True
            other.metadata["lineage_preserved"] = True
            other.metadata["lineage_summary_ids"] = sorted(
                set(other.metadata.get("lineage_summary_ids", [])) | {summary.id}
            )
        await self.graph.update_node(other)

    # ------------------------------------------------------------------ #
    # Phase 1b: Synthesize                                                 #
    # ------------------------------------------------------------------ #

    async def _synthesize_zone(self, result: ConsolidationResult) -> None:
        """
        Find clusters of nodes in the synthesis band and create SUMMARY nodes
        that capture their shared meaning — WITHOUT archiving the originals.

        Synthesis band:
            synthesis_similarity_lower  <=  sim  <  consolidation_similarity_threshold

        This is the primary self-evolution mechanism:
        - Deduplication (Phase 1) collapses near-duplicates into one node
        - Synthesis (this phase) builds HIGHER-LEVEL ABSTRACTIONS from related
          but distinct nodes — connecting ideas that belong together but say
          different things

        Each synthesis summary:
        - Has node_type=SUMMARY, source="agent-synthesizer"
        - Lives at tier=SEMANTIC
        - Is linked to its source nodes via SUMMARIZES edges
        - Has a stable cluster_key so re-running the same cycle updates the
          existing summary rather than creating a new one
        - Originals are left completely intact (only their importance gets a
          small boost to reflect that they've been synthesized)
        """
        lower = self.config.synthesis_similarity_lower
        upper = self.config.consolidation_similarity_threshold

        candidates = await self._sample_candidates()
        embedded = [
            (n, np.array(n.embedding, dtype=np.float32))
            for n in candidates
            if n.embedding is not None
            # Synthesis never archives originals, so pinned nodes are fine here.
            # Only exclude existing SUMMARY nodes (their embeddings are centroids,
            # not raw content, and would create circular synthesis).
            and n.node_type != NodeType.SUMMARY
        ]
        if len(embedded) < 2:
            return

        # ── Build adjacency for synthesis band ──────────────────────────
        adj: dict[str, set[str]] = defaultdict(set)
        sim_map: dict[str, float] = {}

        for i in range(len(embedded)):
            node_a, emb_a = embedded[i]
            for j in range(i + 1, len(embedded)):
                node_b, emb_b = embedded[j]
                sim = float(np.clip(np.dot(emb_a, emb_b), -1.0, 1.0))
                if lower <= sim < upper:
                    adj[node_a.id].add(node_b.id)
                    adj[node_b.id].add(node_a.id)
                    pair_key = min(node_a.id, node_b.id) + max(node_a.id, node_b.id)
                    sim_map[pair_key] = max(sim_map.get(pair_key, 0.0), sim)

        if not adj:
            return

        # ── Cluster connected nodes ──────────────────────────────────────
        id_to_item = {n.id: (n, emb) for n, emb in embedded}
        clusters = self._find_clusters(embedded, adj)

        # ── Cap at batch limit (most important clusters first) ───────────
        clusters.sort(
            key=lambda c: sum(n.importance for n, _ in c) / len(c),
            reverse=True,
        )
        clusters = clusters[: self.config.max_synthesis_batch]

        for cluster in clusters:
            nodes = [n for n, _ in cluster]
            avg_sim = float(np.mean([
                sim_map.get(min(n.id, m.id) + max(n.id, m.id), lower)
                for i, n in enumerate(nodes)
                for m in nodes[i + 1:]
            ] or [lower]))

            await self._upsert_synthesis_summary(nodes, avg_sim, result)

    async def _upsert_synthesis_summary(
        self,
        nodes: list,
        avg_sim: float,
        result: ConsolidationResult,
    ) -> None:
        """
        Create or update a synthesis SUMMARY node for a cluster.
        Originals are kept intact — only a new abstraction node is added.
        """
        import hashlib as _hashlib

        # Stable key based on sorted node IDs so the same cluster always
        # updates the same summary node instead of creating duplicates.
        cluster_key = _hashlib.md5(
            ",".join(sorted(n.id for n in nodes)).encode()
        ).hexdigest()

        # Check if a synthesis summary for this exact cluster already exists
        existing_summaries = await self.graph.list_nodes(
            node_type="summary", limit=10000
        )
        existing = next(
            (
                s for s in existing_summaries
                if (s.metadata or {}).get("synthesis_cluster_key") == cluster_key
                and s.source == "agent-synthesizer"
            ),
            None,
        )

        # Build content via LLM synthesis or structured fallback
        content = await self._build_summary_content(nodes)
        if not content.strip():
            return

        # Centroid embedding of the cluster
        embs = [np.array(n.embedding, dtype=np.float32) for n in nodes if n.embedding]
        avg_emb = np.mean(embs, axis=0).astype(np.float32) if embs else None
        if avg_emb is not None:
            norm = np.linalg.norm(avg_emb)
            if norm > 0:
                avg_emb = avg_emb / norm

        combined_importance = min(0.9, max(n.importance for n in nodes) + 0.05)
        metadata = {
            "synthesis_cluster_key": cluster_key,
            "source_node_ids": [n.id for n in nodes],
            "cluster_size": len(nodes),
            "avg_similarity": avg_sim,
            "synthesized_at": time.time(),
            "llm_synthesized": self._synthesize_fn is not None,
            "connection_index": build_summary_connection_index(
                summary_id=None,
                summary_kind="synthesis",
                source="agent-synthesizer",
                content_hash=self.graph._hash_text(content),
                entries=build_connection_entries(
                    [n.id for n in nodes],
                    relation_type=RelationType.SUMMARIZES,
                    role="source",
                    weight=max(0.5, avg_sim),
                    source="agent-synthesizer",
                ),
            ),
        }

        if existing is None:
            summary_node = MemoryNode(
                collection=self.graph.collection,
                content=content,
                node_type=NodeType.SUMMARY,
                tier=MemoryTier.SEMANTIC,
                importance=combined_importance,
                source="agent-synthesizer",
                parent_node_ids=[n.id for n in nodes],
                tags=["synthesis", "abstraction"],
                metadata=metadata,
            )
            summary_node.metadata["connection_index"] = build_summary_connection_index(
                summary_id=summary_node.id,
                summary_kind="synthesis",
                source="agent-synthesizer",
                content_hash=self.graph._hash_text(content),
                entries=summary_node.metadata["connection_index"]["entries"],
            )
            if avg_emb is not None:
                summary_node.set_embedding(avg_emb)
            await self.graph._storage.upsert_node(summary_node)
            if avg_emb is not None:
                await self.graph._vector_store.upsert(
                    collection=self.graph.collection,
                    node_id=summary_node.id,
                    embedding=avg_emb,
                    content=summary_node.content,
                )
            summary_id = summary_node.id
            result.new_clusters.append(summary_id)
            result.synthesized_summaries.append(summary_id)
        else:
            existing.content = content
            existing.importance = combined_importance
            existing.metadata.update(metadata)
            existing.metadata["connection_index"] = build_summary_connection_index(
                summary_id=existing.id,
                summary_kind="synthesis",
                source="agent-synthesizer",
                content_hash=self.graph._hash_text(content),
                entries=existing.metadata["connection_index"]["entries"],
            )
            existing.parent_node_ids = sorted(set(existing.parent_node_ids) | {n.id for n in nodes})
            if avg_emb is not None:
                existing.set_embedding(avg_emb)
                await self.graph._vector_store.upsert(
                    collection=self.graph.collection,
                    node_id=existing.id,
                    embedding=avg_emb,
                    content=content,
                )
            await self.graph.update_node(existing)
            summary_id = existing.id
            result.synthesized_summaries.append(summary_id)

        # SUMMARIZES edges: summary → each source node
        # Remove stale edges first, then re-add
        for edge in await self.graph.get_edges(summary_id, direction="out"):
            if edge.relation_type == RelationType.SUMMARIZES:
                await self.graph.delete_edge(edge.id)
        for i, node in enumerate(nodes):
            await self.graph.add_edge(
                summary_id, node.id,
                relation_type=RelationType.SUMMARIZES,
                weight=max(0.5, avg_sim - i * 0.02),
                confidence=avg_sim,
                created_by="agent",
                metadata={"synthesis_rank": i + 1},
            )
            # Slightly boost originals — being synthesized signals importance
            if node.importance < 0.9:
                node.importance = min(0.9, node.importance + 0.02)
                await self.graph.update_node(node)

        ids = [n.id[:8] for n in nodes]
        action = "Updated" if existing else "Created"
        result.thoughts.append(
            f"{action} synthesis summary {summary_id[:8]} from {len(nodes)} nodes "
            f"(avg_sim={avg_sim:.3f}, zone=[{self.config.synthesis_similarity_lower:.2f}, "
            f"{self.config.consolidation_similarity_threshold:.2f})). "
            f"Members: {', '.join(ids)}"
        )

    async def _prune_exact_duplicates(self, result: ConsolidationResult) -> None:
        nodes = await self.graph.list_nodes(limit=5000)
        groups: dict[str, list[MemoryNode]] = {}
        for node in nodes:
            key = self._exact_duplicate_key(node)
            if key is None:
                continue
            groups.setdefault(key, []).append(node)

        for key, dup_nodes in groups.items():
            if len(dup_nodes) < 2:
                continue

            dup_nodes.sort(key=self._duplicate_rank, reverse=True)
            canonical = dup_nodes[0]
            for redundant in dup_nodes[1:]:
                await self.graph.delete_node(redundant.id)
                result.pruned_node_ids.append(redundant.id)
                result.thoughts.append(
                    f"Removed exact duplicate node {redundant.id[:8]} and kept {canonical.id[:8]} "
                    f"for duplicate group {key[:24]}."
                )

    def _exact_duplicate_key(self, node: MemoryNode) -> Optional[str]:
        metadata = node.metadata or {}
        if metadata.get("question_key"):
            return f"question:{metadata['question_key']}"
        if metadata.get("document_hash") and metadata.get("chunk") is not None:
            return f"document:{metadata['document_hash']}:{metadata['chunk']}"
        content_hash = metadata.get("content_hash")
        if content_hash:
            return f"content:{node.node_type.value}:{content_hash}"
        normalized = self.graph._hash_text(node.content)
        if normalized:
            return f"content:{node.node_type.value}:{normalized}"
        return None

    def _duplicate_rank(self, node: MemoryNode) -> tuple[int, float, int, float]:
        tier_priority = {
            MemoryTier.WORKING: 5,
            MemoryTier.SEMANTIC: 4,
            MemoryTier.PROCEDURAL: 3,
            MemoryTier.EPISODIC: 2,
            MemoryTier.ARCHIVED: 1,
        }
        return (
            tier_priority.get(node.tier, 0),
            node.importance,
            node.access_count,
            node.last_accessed,
        )

    # ------------------------------------------------------------------ #
    # Phase 2: Prune                                                        #
    # ------------------------------------------------------------------ #

    async def _prune_dead_nodes(self, result: ConsolidationResult) -> None:
        """Delete nodes below the decay threshold (non-pinned, non-summary)."""
        threshold = self.config.prune_importance_threshold

        archived = await self.graph.list_nodes(tier="archived", limit=500)
        for node in archived:
            if node.pinned:
                continue
            node.compute_decay(self.config.decay_half_life_hours)
            if node.decay_score < threshold:
                await self.graph.delete_node(node.id)
                result.pruned_node_ids.append(node.id)
                result.thoughts.append(
                    f"Pruned node {node.id[:8]} (decay={node.decay_score:.4f}, "
                    f"threshold={threshold}). Last accessed "
                    f"{(time.time() - node.last_accessed)/3600:.1f}h ago."
                )

    # ------------------------------------------------------------------ #
    # Phase 3: Cluster rebuild                                             #
    # ------------------------------------------------------------------ #

    async def _rebuild_clusters(self, result: ConsolidationResult) -> None:
        """
        Ensure working memory cluster reflects current hot nodes.
        Other cluster types are left to the application to manage.
        """
        clusters = await self.graph.list_clusters()
        working_cluster: Optional[MemoryCluster] = next(
            (c for c in clusters if c.cluster_type == ClusterType.WORKING), None
        )

        if working_cluster is None:
            working_cluster = await self.graph.add_cluster(
                name="working_memory",
                cluster_type=ClusterType.WORKING,
            )
            result.new_clusters.append(working_cluster.id)

        # Update working cluster membership
        hot_nodes = await self.graph.list_nodes(tier="working", limit=1000)
        working_cluster.node_ids = [n.id for n in hot_nodes]
        await self.graph.update_cluster(working_cluster)

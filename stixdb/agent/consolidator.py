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
from typing import Optional

import numpy as np

from stixdb.graph.node import MemoryNode, NodeType, MemoryTier
from stixdb.graph.edge import RelationEdge, RelationType
from stixdb.graph.cluster import MemoryCluster, ClusterType
from stixdb.graph.memory_graph import MemoryGraph
from stixdb.config import AgentConfig
from stixdb.observability.tracer import get_tracer


class ConsolidationResult:
    """Result report from a single consolidation cycle."""
    def __init__(self) -> None:
        self.merged_pairs: list[tuple[str, str, str]] = []   # (src_id, tgt_id, summary_id)
        self.pruned_node_ids: list[str] = []
        self.new_clusters: list[str] = []
        self.thoughts: list[str] = []    # Human-readable agent reasoning

    def to_dict(self) -> dict:
        return {
            "merged_count": len(self.merged_pairs),
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

    def __init__(self, graph: MemoryGraph, config: AgentConfig) -> None:
        self.graph = graph
        self.config = config
        self._tracer = get_tracer()

    async def run_cycle(self) -> ConsolidationResult:
        """
        Run one full consolidation cycle:
        1. Find merge candidates (high semantic similarity)
        2. Prune dead nodes (low decay score, not pinned)
        3. Build/update clusters
        """
        result = ConsolidationResult()

        # Phase 1: Merge candidates
        await self._find_and_merge(result)

        # Phase 1b: Remove exact duplicates while keeping one canonical node.
        await self._prune_exact_duplicates(result)

        # Phase 2: Prune dead nodes
        await self._prune_dead_nodes(result)

        # Phase 3: Update clusters
        await self._rebuild_clusters(result)

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
        """Identify semantically similar nodes and merge them."""
        threshold = self.config.consolidation_similarity_threshold
        batch_size = self.config.max_consolidation_batch

        # Fetch a representative batch of non-pinned semantic/episodic nodes
        candidates = await self.graph.list_nodes(
            tier="semantic", limit=batch_size // 2
        )
        candidates += await self.graph.list_nodes(
            tier="episodic", limit=batch_size // 2
        )

        # Filter nodes that have embeddings
        embedded = [(n, np.array(n.embedding, dtype=np.float32))
                    for n in candidates if n.embedding is not None and not n.pinned]

        if len(embedded) < 2:
            return

        # Pairwise cosine similarity check (upper triangle only)
        merged_ids: set[str] = set()

        for i in range(len(embedded)):
            if embedded[i][0].id in merged_ids:
                continue
            node_a, emb_a = embedded[i]

            for j in range(i + 1, len(embedded)):
                if embedded[j][0].id in merged_ids:
                    continue
                node_b, emb_b = embedded[j]

                sim = float(np.clip(np.dot(emb_a, emb_b), -1.0, 1.0))  # Already normalised, but guard float drift
                if sim >= threshold:
                    # If one node is already a SUMMARY, absorb the other into it
                    # rather than creating a redundant third summary node.
                    if node_a.node_type == NodeType.SUMMARY:
                        await self._absorb_into_summary(node_a, emb_a, node_b, sim)
                        summary_id = node_a.id
                        thought = (
                            f"Absorbed node {node_b.id[:8]} into existing summary "
                            f"{node_a.id[:8]} (similarity={sim:.3f}). "
                            f"Summary updated: '{node_a.content[:40]}...'"
                        )
                    elif node_b.node_type == NodeType.SUMMARY:
                        await self._absorb_into_summary(node_b, emb_b, node_a, sim)
                        summary_id = node_b.id
                        thought = (
                            f"Absorbed node {node_a.id[:8]} into existing summary "
                            f"{node_b.id[:8]} (similarity={sim:.3f}). "
                            f"Summary updated: '{node_b.content[:40]}...'"
                        )
                    else:
                        summary_id = await self._merge_nodes(node_a, node_b, sim)
                        thought = (
                            f"Merged nodes {node_a.id[:8]} and {node_b.id[:8]} "
                            f"(similarity={sim:.3f} ≥ threshold={threshold:.3f}). "
                            f"Both related to '{node_a.content[:40]}...' — created summary node {summary_id[:8]}."
                        )
                    merged_ids.add(node_a.id)
                    merged_ids.add(node_b.id)
                    result.merged_pairs.append((node_a.id, node_b.id, summary_id))
                    result.thoughts.append(thought)
                    break  # Only merge each node once per cycle

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
            },
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

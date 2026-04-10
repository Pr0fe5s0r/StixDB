"""
RelationWeaver — autonomous relation discovery between memory nodes.

The RelationWeaver is the "cataloging" module of the Librarian Agent.
It proactively discovers semantic relationships between nodes that are
*related but distinct* — too different to merge, but too connected to ignore.

Operates in the "relation band":
  lower bound  → config.relation_similarity_lower  (default 0.40)
  upper bound  → config.consolidation_similarity_threshold (default 0.88)

Within this band, pairs of nodes are candidates for a RELATES_TO (or
typed) edge. The weaver:
  1. Samples a rotating, multi-tier batch of nodes
  2. Computes pairwise cosine similarity
  3. For pairs in the relation band without an existing edge:
       - Calls the optional LLM classify_fn for relation type + confidence
       - Falls back to a heuristic confidence estimate
  4. Creates an edge ONLY when confidence >= 0.80
     (the 80% certainty rule — ~20% of candidates are skipped)
  5. Caches evaluated pairs to avoid redundant work across cycles

The weaver is *additive*: it never modifies or deletes existing edges.
All edges it creates carry created_by="librarian" and a metadata dict
with similarity, description, and cycle index.
"""
from __future__ import annotations

import hashlib
import time
from typing import Awaitable, Callable, Optional

import numpy as np
import structlog

from stixdb.graph.memory_graph import MemoryGraph
from stixdb.graph.node import MemoryNode, NodeType
from stixdb.graph.edge import RelationType
from stixdb.config import AgentConfig

logger = structlog.get_logger(__name__)

# Minimum confidence required to create an edge
CONFIDENCE_GATE = 0.80


class WeaverResult:
    """Result report from one weaving pass."""

    def __init__(self) -> None:
        self.edges_created: list[tuple[str, str, RelationType, float]] = []
        self.pairs_skipped: int = 0
        self.thoughts: list[str] = []

    def to_dict(self) -> dict:
        return {
            "edges_created": len(self.edges_created),
            "pairs_skipped": self.pairs_skipped,
            "thoughts": self.thoughts,
        }


class RelationWeaver:
    """
    Autonomous relation discovery engine.

    One instance per collection. Runs inside the agent's background cycle.
    """

    def __init__(
        self,
        graph: MemoryGraph,
        config: AgentConfig,
        classify_fn: Optional[
            Callable[
                [MemoryNode, MemoryNode],
                Awaitable[tuple[RelationType, float, str]],
            ]
        ] = None,
    ) -> None:
        self.graph = graph
        self.config = config
        # LLM hook: (node_a, node_b) → (RelationType, confidence 0–1, description str)
        self._classify_fn = classify_fn
        # Cache of already-evaluated pair keys (frozenset-hash) to avoid re-work
        self._woven_pairs: set[str] = set()
        self._cycle = 0

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    async def run_pass(self) -> WeaverResult:
        """
        One weaving pass:
          1. Sample a rotating batch of active nodes
          2. Find pairs in the relation band
          3. Classify each pair and create an edge if confidence >= 0.80
        """
        result = WeaverResult()

        lower = self.config.relation_similarity_lower
        upper = self.config.consolidation_similarity_threshold

        candidates = await self._sample_candidates()
        embedded = [
            (n, np.array(n.embedding, dtype=np.float32))
            for n in candidates
            if n.embedding is not None
            # SUMMARY nodes have synthetic centroid embeddings — skip to avoid
            # false relations between summaries and their source clusters
            and n.node_type != NodeType.SUMMARY
        ]
        if len(embedded) < 2:
            return result

        # Fetch existing edges for the sampled nodes (to skip already-connected pairs)
        existing_pairs = await self._get_existing_edge_pairs(embedded)

        # ── Find relation-band pairs ─────────────────────────────────────
        relation_pairs: list[tuple[MemoryNode, MemoryNode, float]] = []
        for i in range(len(embedded)):
            node_a, emb_a = embedded[i]
            for j in range(i + 1, len(embedded)):
                node_b, emb_b = embedded[j]

                pair_key = self._pair_key(node_a.id, node_b.id)
                if pair_key in self._woven_pairs:
                    result.pairs_skipped += 1
                    continue

                # Already connected — mark as seen and skip
                if (node_a.id, node_b.id) in existing_pairs or (node_b.id, node_a.id) in existing_pairs:
                    self._woven_pairs.add(pair_key)
                    result.pairs_skipped += 1
                    continue

                sim = float(np.clip(np.dot(emb_a, emb_b), -1.0, 1.0))
                if lower <= sim < upper:
                    relation_pairs.append((node_a, node_b, sim))

        # Sort strongest first so limited budget goes to best candidates
        relation_pairs.sort(key=lambda x: x[2], reverse=True)

        # ── Weave edges ──────────────────────────────────────────────────
        batch_limit = self.config.weaver_batch_limit
        for node_a, node_b, sim in relation_pairs[:batch_limit]:
            pair_key = self._pair_key(node_a.id, node_b.id)
            rel_type, confidence, description = await self._classify_relation(node_a, node_b, sim)

            self._woven_pairs.add(pair_key)  # mark regardless of outcome

            if confidence < CONFIDENCE_GATE:
                result.pairs_skipped += 1
                result.thoughts.append(
                    f"Skipped {node_a.id[:8]}↔{node_b.id[:8]} "
                    f"(sim={sim:.3f}, confidence={confidence:.2f} < {CONFIDENCE_GATE})"
                )
                continue

            await self.graph.add_edge(
                source_id=node_a.id,
                target_id=node_b.id,
                relation_type=rel_type,
                weight=sim,
                confidence=confidence,
                created_by="librarian",
                metadata={
                    "similarity": sim,
                    "description": description,
                    "woven_at": time.time(),
                    "woven_cycle": self._cycle,
                },
            )

            result.edges_created.append((node_a.id, node_b.id, rel_type, confidence))
            result.thoughts.append(
                f"Wove {node_a.id[:8]} --[{rel_type.value}:{confidence:.2f}]--> "
                f"{node_b.id[:8]}  sim={sim:.3f}. {description}"
            )

        self._cycle += 1
        return result

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _pair_key(self, id_a: str, id_b: str) -> str:
        """Canonical, order-independent hash key for a node pair."""
        ordered = min(id_a, id_b) + max(id_a, id_b)
        return hashlib.md5(ordered.encode()).hexdigest()

    async def _classify_relation(
        self,
        node_a: MemoryNode,
        node_b: MemoryNode,
        similarity: float,
    ) -> tuple[RelationType, float, str]:
        """
        Determine the relation type and confidence for a node pair.

        Uses the optional LLM classify_fn if wired up.
        Falls back to a heuristic based on similarity magnitude:
          - sim ≥ 0.70 → RELATES_TO, confidence ≈ sim × 0.95  (≥ 0.665)
          - sim ≥ 0.60 → RELATES_TO, confidence ≈ sim × 0.90  (≥ 0.54)
          - sim ≥ 0.50 → RELATES_TO, confidence ≈ sim × 0.87  (≥ 0.435)
          - sim ≥ 0.40 → RELATES_TO, confidence ≈ sim × 0.82  (≥ 0.328)
        With lower bound at 0.40 and gate at 0.80, the heuristic passes
        edges for sim ≥ ~0.843 without LLM.  With LLM the gate applies
        to the LLM-returned confidence directly.
        """
        if self._classify_fn is not None:
            try:
                return await self._classify_fn(node_a, node_b)
            except Exception as exc:
                logger.debug("LLM classify_fn failed, using heuristic", error=str(exc))

        # Heuristic fallback
        if similarity >= 0.70:
            confidence = similarity * 0.95
        elif similarity >= 0.60:
            confidence = similarity * 0.90
        elif similarity >= 0.50:
            confidence = similarity * 0.87
        else:
            confidence = similarity * 0.82

        return RelationType.RELATES_TO, confidence, "Heuristic semantic relation"

    async def _sample_candidates(self) -> list[MemoryNode]:
        """
        Sample a rotating, multi-tier batch of active nodes.

        Same rotation strategy as the Consolidator to ensure full coverage
        over many cycles. Working-tier nodes are always included since they
        are the most recently relevant and most likely to form useful edges.
        """
        batch = self.config.weaver_batch_size
        per_tier = max(4, batch // 3)
        offset = (self._cycle * per_tier) % max(1, per_tier * 10)

        working  = await self.graph.list_nodes(tier="working",  limit=per_tier,     offset=0)
        semantic = await self.graph.list_nodes(tier="semantic", limit=per_tier,     offset=offset)
        episodic = await self.graph.list_nodes(tier="episodic", limit=per_tier * 2, offset=offset)

        seen: set[str] = set()
        merged: list[MemoryNode] = []
        for node in working + semantic + episodic:
            if node.id not in seen:
                seen.add(node.id)
                merged.append(node)

        # Bias toward high-importance nodes
        merged.sort(key=lambda n: n.importance, reverse=True)
        return merged[:batch]

    async def _get_existing_edge_pairs(
        self,
        embedded: list[tuple[MemoryNode, object]],
    ) -> set[tuple[str, str]]:
        """
        Collect (source_id, target_id) pairs for edges already in the graph.

        Only checks the working-tier nodes (hot slice) to keep this O(W×E)
        rather than O(N×E). Cold nodes rarely have edges; missing them here
        just means the weaver might try and discover a duplicate, but the
        pair_key cache will prevent actually duplicating it after cycle 1.
        """
        pairs: set[tuple[str, str]] = set()
        hot = [node for node, _ in embedded if node.tier.value == "working"][:20]
        for node in hot:
            try:
                edges = await self.graph.get_edges(node.id)
                for edge in edges:
                    pairs.add((edge.source_id, edge.target_id))
            except Exception:
                pass
        return pairs

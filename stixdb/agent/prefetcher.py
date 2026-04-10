"""
PredictivePrefetcher â€” proactive working-memory pre-warming.

The PredictivePrefetcher is the "anticipation" module of the Librarian Agent.
It learns from past query patterns and pre-promotes nodes into working memory
BEFORE the question is asked â€” so the retrieval pipeline finds hot nodes
instead of cold ones.

How it works:
  1. Every query is recorded: (query_embedding, retrieved_node_ids, timestamp)
  2. On each agent cycle, for each incoming "context signal" (new query embedding
     OR existing hot-node neighborhood), the prefetcher:
       a. Finds the K most similar past queries via cosine similarity
       b. Collects the nodes those queries retrieved â€” these are likely needed again
       c. Promotes them to WORKING tier if they're not already hot
  3. Additionally, it "fans out" from currently hot nodes by promoting their
     direct graph neighbors (depth=1) â€” the librarian's "adjacent shelf" heuristic

The 80/20 rule: ~80% of likely-relevant nodes are pre-loaded based on pattern
matching. The remaining ~20% uncertainty is acknowledged by NOT pre-loading
nodes whose query-match confidence is below the threshold.

All pre-promotions are soft (importance += small boost, tier â†’ working).
They're temporary: the AccessPlanner will demote them if they're never actually
accessed.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Optional

import numpy as np
import structlog

from stixdb.graph.memory_graph import MemoryGraph
from stixdb.graph.node import MemoryNode, MemoryTier, NodeType
from stixdb.graph.summary_index import extract_summary_connection_entries
from stixdb.config import AgentConfig

logger = structlog.get_logger(__name__)

# Minimum query-similarity to consider a past query "relevant"
QUERY_MATCH_THRESHOLD = 0.65

# How much to boost importance when pre-promoting a node
PREFETCH_IMPORTANCE_BOOST = 0.03


class QueryRecord:
    """A single recorded query event."""
    __slots__ = ("embedding", "node_ids", "ts")

    def __init__(self, embedding: np.ndarray, node_ids: list[str], ts: float) -> None:
        self.embedding = embedding
        self.node_ids = node_ids
        self.ts = ts


class PrefetchResult:
    """Result from one prefetch cycle."""

    def __init__(self) -> None:
        self.promoted: list[str] = []      # node IDs promoted to working
        self.fan_out: list[str] = []       # node IDs promoted via neighbor fan-out
        self.thoughts: list[str] = []

    def to_dict(self) -> dict:
        return {
            "prefetch_promoted": len(self.promoted),
            "fanout_promoted": len(self.fan_out),
            "thoughts": self.thoughts,
        }


class PredictivePrefetcher:
    """
    Predictive working-memory pre-warming agent.

    One instance per collection. Records query patterns and proactively
    promotes likely-needed nodes to the WORKING tier.
    """

    def __init__(self, graph: MemoryGraph, config: AgentConfig) -> None:
        self.graph = graph
        self.config = config
        # Rolling window of past query events
        self._history: deque[QueryRecord] = deque(
            maxlen=self.config.prefetch_history_size
        )
        # Set of node IDs already in working memory (maintained locally for speed)
        self._working_ids: set[str] = set()

    # ------------------------------------------------------------------ #
    # Feed API â€” called from the ContextBroker on every query             #
    # ------------------------------------------------------------------ #

    def record_query(
        self,
        query_embedding: np.ndarray,
        retrieved_node_ids: list[str],
    ) -> None:
        """
        Record a completed query and the nodes it retrieved.

        Called by the ContextBroker after every retrieval so the prefetcher
        can learn from real access patterns.
        """
        self._history.append(
            QueryRecord(
                embedding=np.array(query_embedding, dtype=np.float32),
                node_ids=list(retrieved_node_ids),
                ts=time.time(),
            )
        )

    # ------------------------------------------------------------------ #
    # Agent cycle entry point                                             #
    # ------------------------------------------------------------------ #

    async def run_pass(
        self,
        pending_query_embedding: Optional[np.ndarray] = None,
    ) -> PrefetchResult:
        """
        One prefetch pass â€” two phases:
          1. Pattern-match: if a new query embedding is available, find similar
             past queries and pre-promote their nodes.
          2. Fan-out: promote graph neighbors of currently hot working nodes.

        Args:
            pending_query_embedding: The embedding of a query that has just been
                submitted but not yet answered. When provided, the prefetcher
                can pre-load before the broker even runs retrieval.
        """
        result = PrefetchResult()

        # Sync our local working_ids cache
        working_nodes = await self.graph.list_nodes(tier="working", limit=10_000)
        self._working_ids = {n.id for n in working_nodes}

        # â”€â”€ Phase 1: Pattern-match prefetch â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if pending_query_embedding is not None and len(self._history) > 0:
            await self._pattern_prefetch(pending_query_embedding, result)

        # â”€â”€ Phase 2: Neighbor fan-out â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if self.config.enable_neighbor_fanout:
            await self._neighbor_fanout(working_nodes, result)

        return result

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    async def _pattern_prefetch(
        self,
        query_emb: np.ndarray,
        result: PrefetchResult,
    ) -> None:
        """
        Find similar past queries and pre-promote their nodes.

        Only promotes nodes whose query-match confidence >= QUERY_MATCH_THRESHOLD
        (the 80% rule in practice: ~0.65 cosine similarity to past queries).
        """
        query_emb = query_emb / (np.linalg.norm(query_emb) + 1e-9)

        # Score all history records
        scored: list[tuple[float, QueryRecord]] = []
        for record in self._history:
            hist_emb = record.embedding / (np.linalg.norm(record.embedding) + 1e-9)
            sim = float(np.clip(np.dot(query_emb, hist_emb), -1.0, 1.0))
            if sim >= QUERY_MATCH_THRESHOLD:
                scored.append((sim, record))

        if not scored:
            return

        # Collect candidate node IDs weighted by similarity
        scored.sort(key=lambda x: x[0], reverse=True)
        top_k_records = scored[:self.config.prefetch_top_k_records]

        candidate_node_ids: dict[str, float] = {}
        for sim, record in top_k_records:
            for nid in record.node_ids:
                # Weight: similarity * recency (nodes from very old queries get discount)
                age_hours = (time.time() - record.ts) / 3600.0
                recency = 2.0 ** (-age_hours / 24.0)  # half-life = 24 hours
                score = sim * recency
                candidate_node_ids[nid] = max(candidate_node_ids.get(nid, 0.0), score)

        # Sort and limit
        sorted_candidates = sorted(candidate_node_ids.items(), key=lambda x: x[1], reverse=True)
        limit = self.config.prefetch_max_promote
        to_promote = [nid for nid, _ in sorted_candidates[:limit] if nid not in self._working_ids]

        for node_id in to_promote:
            node = await self.graph.get_node(node_id)
            if node is None or node.pinned:
                continue
            node.tier = MemoryTier.WORKING
            node.importance = min(1.0, node.importance + PREFETCH_IMPORTANCE_BOOST)
            await self.graph.update_node(node)
            self._working_ids.add(node_id)
            result.promoted.append(node_id)

        if to_promote:
            top_sim = scored[0][0]
            result.thoughts.append(
                f"Pattern-prefetch: promoted {len(to_promote)} nodes "
                f"(top query_sim={top_sim:.3f}, {len(scored)} matching records)"
            )

    async def _neighbor_fanout(
        self,
        working_nodes: list[MemoryNode],
        result: PrefetchResult,
    ) -> None:
        """
        Fan out from hot nodes: promote their direct graph neighbors.

        Summary nodes can now provide a direct connection index, so we use that
        first and only fall back to graph traversal when the metadata is absent
        or fails to hydrate anything.
        """
        hot_nodes = sorted(working_nodes, key=lambda n: n.access_count, reverse=True)
        hot_nodes = hot_nodes[:self.config.fanout_hot_node_limit]
        hot_node_map = {node.id: node for node in hot_nodes}

        summary_related_ids: list[str] = []
        summary_related_scores: dict[str, float] = {}
        summary_seed_related_ids: dict[str, list[str]] = {}
        fallback_hot_node_ids: list[str] = []

        for hot_node in hot_nodes:
            if hot_node.node_type == NodeType.SUMMARY:
                entries = extract_summary_connection_entries(hot_node.metadata or {})
                if entries:
                    access_multiplier = 1.0 + min(0.5, hot_node.access_count / 50.0)
                    related_ids: list[str] = []
                    limit = max(4, self.config.prefetch_max_fanout)
                    for entry in entries[:limit]:
                        node_id = str(entry.get("node_id") or "").strip()
                        if not node_id or node_id in self._working_ids:
                            continue
                        related_ids.append(node_id)
                        weight = max(0.1, float(entry.get("weight", 1.0) or 1.0))
                        rank = max(1, int(entry.get("rank", 1) or 1))
                        score = access_multiplier * weight / rank
                        summary_related_scores[node_id] = max(
                            summary_related_scores.get(node_id, 0.0),
                            score,
                        )
                    if related_ids:
                        summary_seed_related_ids[hot_node.id] = related_ids
                        summary_related_ids.extend(related_ids)
                        continue
            fallback_hot_node_ids.append(hot_node.id)

        promoted_count = 0

        if summary_related_ids:
            related_nodes = await self.graph.get_nodes(list(dict.fromkeys(summary_related_ids)))
            related_node_ids = {node.id for node in related_nodes}
            promoted_candidates: list[tuple[float, MemoryNode]] = []
            for node in related_nodes:
                if node.id in self._working_ids or node.pinned:
                    continue
                promoted_candidates.append((summary_related_scores.get(node.id, 0.0), node))
            promoted_candidates.sort(key=lambda item: item[0], reverse=True)

            for _, node in promoted_candidates:
                if promoted_count >= self.config.prefetch_max_fanout:
                    break
                node.tier = MemoryTier.WORKING
                node.importance = min(1.0, node.importance + PREFETCH_IMPORTANCE_BOOST)
                await self.graph.update_node(node)
                self._working_ids.add(node.id)
                result.fan_out.append(node.id)
                promoted_count += 1

            for seed_id, related_ids in summary_seed_related_ids.items():
                if not any(node_id in related_node_ids for node_id in related_ids):
                    fallback_hot_node_ids.append(seed_id)

        fallback_hot_node_ids = list(dict.fromkeys(fallback_hot_node_ids))
        if promoted_count < self.config.prefetch_max_fanout:
            for hot_id in fallback_hot_node_ids:
                hot_node = hot_node_map.get(hot_id)
                if hot_node is None:
                    continue
                try:
                    neighbors = await self.graph.get_neighbours(
                        hot_node.id,
                        direction="both",
                        max_depth=1,
                    )
                except Exception:
                    continue

                for neighbor in neighbors:
                    if promoted_count >= self.config.prefetch_max_fanout:
                        break
                    if neighbor.id in self._working_ids:
                        continue
                    if neighbor.pinned:
                        continue
                    neighbor.tier = MemoryTier.WORKING
                    neighbor.importance = min(1.0, neighbor.importance + PREFETCH_IMPORTANCE_BOOST)
                    await self.graph.update_node(neighbor)
                    self._working_ids.add(neighbor.id)
                    result.fan_out.append(neighbor.id)
                    promoted_count += 1

                if promoted_count >= self.config.prefetch_max_fanout:
                    break

        if promoted_count:
            result.thoughts.append(
                f"Neighbor fan-out: promoted {promoted_count} nodes "
                f"from {len(hot_nodes)} hot nodes (summary hints first)"
            )

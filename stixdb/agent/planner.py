"""
AccessPlanner — tracks access patterns and drives tier promotions.

This component implements a hybrid LRU + LFU (Least Recently Used /
Least Frequently Used) scoring algorithm — similar to how modern OS
page-replacement policies work — to determine which nodes are "hot"
(should live in Working Memory) and which are "cold" (candidates for
archival or pruning).
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

from stixdb.graph.node import MemoryNode, MemoryTier
from stixdb.graph.memory_graph import MemoryGraph
from stixdb.config import AgentConfig


@dataclass
class AccessRecord:
    """Access history for a single node."""
    node_id: str
    total_accesses: int = 0
    last_accessed: float = field(default_factory=time.time)
    access_log: deque = field(default_factory=lambda: deque(maxlen=100))

    def record(self) -> None:
        now = time.time()
        self.total_accesses += 1
        self.last_accessed = now
        self.access_log.append(now)

    def recency_score(self, now: Optional[float] = None) -> float:
        """Score based on how recently the node was accessed (0-1)."""
        now = now or time.time()
        elapsed_hours = (now - self.last_accessed) / 3600.0
        # Exponential decay: 1.0 immediately, ~0.5 after 12h, ~0.01 after 72h
        return 2.0 ** (-elapsed_hours / 12.0)

    def frequency_score(self, window_hours: float = 24.0) -> float:
        """Score based on access frequency within the time window (0-1)."""
        now = time.time()
        cutoff = now - (window_hours * 3600.0)
        recent_accesses = sum(1 for t in self.access_log if t >= cutoff)
        # Normalise — 10 accesses in 24h = max score
        return min(1.0, recent_accesses / 10.0)

    def combined_score(self, alpha: float = 0.6) -> float:
        """
        Weighted combination: alpha * frequency + (1-alpha) * recency.
        By default, frequency weighs more.
        """
        return alpha * self.frequency_score() + (1.0 - alpha) * self.recency_score()


class AccessPlanner:
    """
    Monitors access patterns across all nodes in a collection
    and produces promotion / demotion decisions for the Memory Agent.
    """

    def __init__(self, graph: MemoryGraph, config: AgentConfig) -> None:
        self.graph = graph
        self.config = config
        # In-memory access records (ephemeral OK; we want real-time responsiveness)
        self._records: dict[str, AccessRecord] = defaultdict(
            lambda: AccessRecord(node_id="")
        )
        self._working_memory_ids: set[str] = set()

    def record_access(self, node_id: str) -> None:
        """Called every time a node is retrieved. Thread-safe (GIL)."""
        if node_id not in self._records:
            self._records[node_id] = AccessRecord(node_id=node_id)
        self._records[node_id].record()

    def get_score(self, node_id: str) -> float:
        rec = self._records.get(node_id)
        if rec is None:
            return 0.0
        return rec.combined_score()

    async def plan(self) -> dict[str, list[MemoryNode]]:
        """
        Analyse all tracked nodes and return promotion / demotion lists.
        
        Returns: {
            "promote_to_working": [...],
            "demote_from_working": [...],
            "candidates_for_archive": [...],
        }
        """
        all_nodes = await self.graph.list_nodes(limit=50_000)
        now = time.time()

        promote: list[MemoryNode] = []
        demote: list[MemoryNode] = []
        archive: list[MemoryNode] = []

        hot_threshold = 0.65
        archive_threshold = 0.08

        for node in all_nodes:
            if node.pinned:
                continue

            score = self.get_score(node.id)
            in_working = node.tier == MemoryTier.WORKING

            # Compute natural decay
            node.compute_decay(self.config.decay_half_life_hours)

            if score >= hot_threshold and not in_working:
                # New hot node — promote to working memory
                if len(self._working_memory_ids) < self.config.working_memory_max_nodes:
                    promote.append(node)

            elif score < hot_threshold * 0.4 and in_working:
                # Node has gone cold — demote from working memory
                demote.append(node)
                self._working_memory_ids.discard(node.id)

            if node.decay_score < archive_threshold and not node.pinned:
                archive.append(node)

        return {
            "promote_to_working": promote,
            "demote_from_working": demote,
            "candidates_for_archive": archive,
        }

    async def apply_promotions(self, plan: dict[str, list[MemoryNode]]) -> None:
        """Apply tier promotion/demotion decisions to the graph."""
        for node in plan.get("promote_to_working", []):
            node.tier = MemoryTier.WORKING
            node.importance = min(1.0, node.importance + 0.05)
            await self.graph.update_node(node)
            self._working_memory_ids.add(node.id)

        for node in plan.get("demote_from_working", []):
            node.tier = MemoryTier.SEMANTIC
            await self.graph.update_node(node)

    def get_hot_node_ids(self) -> list[str]:
        """Return IDs of all nodes currently in working memory."""
        return list(self._working_memory_ids)

    def get_stats(self) -> dict:
        return {
            "tracked_nodes": len(self._records),
            "working_memory_size": len(self._working_memory_ids),
            "top_accessed": sorted(
                [
                    {"node_id": nid[:8], "score": rec.combined_score(), "total": rec.total_accesses}
                    for nid, rec in self._records.items()
                ],
                key=lambda x: x["score"],
                reverse=True,
            )[:10],
        }

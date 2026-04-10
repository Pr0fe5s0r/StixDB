"""
MemoryAgent — top-level agent orchestrator per collection.

The MemoryAgent is the "brain" that lives inside a StixDB collection.
It owns:
  - AccessPlanner        (tracks hot/cold nodes)
  - Consolidator         (merges + prunes memory)
  - RelationWeaver       (discovers typed edges between related nodes)
  - PredictivePrefetcher (pre-warms working memory from query patterns)
  - MemoryAgentWorker    (decoupled async background loop)

It exposes a simple API so the StixDBEngine can interact with it
without needing to know the internals.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

import numpy as np

from stixdb.graph.memory_graph import MemoryGraph
from stixdb.agent.planner import AccessPlanner
from stixdb.agent.consolidator import Consolidator
from stixdb.agent.weaver import RelationWeaver
from stixdb.agent.prefetcher import PredictivePrefetcher
from stixdb.agent.worker import MemoryAgentWorker
from stixdb.config import AgentConfig


class MemoryAgent:
    """
    Per-collection autonomous memory agent.

    Lifecycle:
        agent = MemoryAgent(graph, config)
        await agent.start()   # begins background loop
        # ... system runs ...
        await agent.stop()    # graceful shutdown
    """

    def __init__(
        self,
        graph: MemoryGraph,
        config: AgentConfig,
        synthesize_fn: Optional[Callable[[list[Any]], Awaitable[str]]] = None,
        classify_fn: Optional[
            Callable[[Any, Any], Awaitable[tuple[Any, float, str]]]
        ] = None,
    ) -> None:
        self.graph = graph
        self.config = config

        self.planner = AccessPlanner(graph, config)
        self.consolidator = Consolidator(graph, config, synthesize_fn=synthesize_fn)
        self.weaver = RelationWeaver(graph, config, classify_fn=classify_fn)
        self.prefetcher = PredictivePrefetcher(graph, config)
        self.worker = MemoryAgentWorker(
            graph=graph,
            planner=self.planner,
            consolidator=self.consolidator,
            weaver=self.weaver,
            prefetcher=self.prefetcher,
            config=config,
        )

    def set_maintenance_callback(
        self,
        callback: Optional[Callable[[], Awaitable[dict]]],
    ) -> None:
        self.worker.set_maintenance_callback(callback)

    async def start(self) -> None:
        """Start the background agent loop."""
        await self.worker.start()

    async def stop(self) -> None:
        """Stop the background agent loop gracefully."""
        await self.worker.stop()

    def record_access(self, node_id: str) -> None:
        """
        Notify the agent that a node was accessed.
        Called by the Context Broker on every retrieval.
        """
        self.worker.record_access(node_id)

    def record_query_for_prefetch(
        self,
        query_embedding: np.ndarray,
        retrieved_node_ids: list[str],
    ) -> None:
        """
        Feed a completed query into the prefetcher's pattern history.
        Called by the ContextBroker after every retrieval.
        """
        self.prefetcher.record_query(query_embedding, retrieved_node_ids)

    async def prefetch_for_query(self, query_embedding: np.ndarray) -> None:
        """
        Trigger an immediate prefetch pass for a pending query embedding.
        Called by the ContextBroker BEFORE retrieval so hot nodes are ready.
        """
        if self.config.enable_predictive_prefetch:
            await self.prefetcher.run_pass(pending_query_embedding=query_embedding)

    async def run_cycle_now(self) -> dict:
        """
        Trigger an immediate agent cycle (useful for testing / on-demand).
        Returns the cycle result summary.
        """
        plan = await self.planner.plan()
        await self.planner.apply_promotions(plan)
        result = await self.consolidator.run_cycle()
        return result.to_dict()

    def get_status(self) -> dict:
        return self.worker.get_status()

    @property
    def is_running(self) -> bool:
        return self.worker.is_running

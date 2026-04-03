"""
Context Broker — the smart query router between external agents and StixDB.

The Broker is the single entry point for all agentic queries. It performs
the full retrieval pipeline:

  1. Embed the query
  2. Semantic vector search (fast approximate retrieval)
  3. Graph expansion (BFS from seed nodes for contextual depth)
  4. Tier-aware re-ranking (working memory nodes get a boost)
  5. Truncate to LLM context window limit
  6. Pass to Reasoner for synthesis
  7. Record all accesses with the Agent planner
  8. Return ContextResponse

All of this happens inside the DB — the calling agent gets back
a structured, reasoned answer, not a bag of documents.
"""
from __future__ import annotations

import time
from typing import Optional

from stixdb.graph.memory_graph import MemoryGraph
from stixdb.graph.node import MemoryNode, MemoryTier
from stixdb.agent.reasoner import Reasoner
from stixdb.agent.memory_agent import MemoryAgent
from stixdb.context.response import ContextResponse, SourceNode
from stixdb.config import ReasonerConfig
from stixdb.observability.tracer import get_tracer

import structlog

logger = structlog.get_logger(__name__)


class ContextBroker:
    """
    Agentic query router for a single collection.
    
    Owned by the StixDBEngine — one broker per collection.
    """

    def __init__(
        self,
        graph: MemoryGraph,
        agent: MemoryAgent,
        reasoner_config: ReasonerConfig,
        verbose: bool = True,
    ) -> None:
        self.graph = graph
        self.agent = agent
        self.reasoner = Reasoner(reasoner_config)
        self._verbose = verbose
        self._tracer = get_tracer()

    async def ask(
        self,
        question: str,
        top_k: int = 15,
        search_threshold: float = 0.25,
        graph_depth: int = 2,
        working_memory_boost: float = 0.15,
        system_prompt: Optional[str] = None,
        output_schema: Optional[dict] = None,
        history: Optional[list[dict]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        enable_reflection_cache: bool = True,
        query_origin: str = "user",
    ) -> ContextResponse:
        """
        Process a natural-language question and return a ContextResponse.
        
        Args:
            question: The question asked by an external agent.
            top_k: Max vector search results.
            search_threshold: Minimum cosine similarity to include a node.
            graph_depth: BFS depth for graph expansion from seed nodes.
            working_memory_boost: Score bonus for nodes in working memory.
        
        Returns:
            ContextResponse with answer, reasoning trace, and sources.
        """
        start = time.time()

        # ── Phase 1-3: Prepare Context ───────────────────────────────────
        final_nodes, final_scores, candidates = await self.prepare_context(
            query=question,
            top_k=top_k,
            threshold=search_threshold,
            depth=graph_depth,
            working_memory_boost=working_memory_boost,
        )

        # ── Phase 4: Notify agent of access events ────────────────────────
        for node in final_nodes:
            self.agent.record_access(node.id)
            await self.graph.touch_node(node.id)

        # ── Phase 5: LLM Reasoning ───────────────────────────────────────
        reasoning_result = await self.reasoner.reason(
            collection=self.graph.collection,
            question=question,
            nodes=final_nodes,
            history=history,
            system_prompt=system_prompt,
            output_schema=output_schema,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        latency_ms = (time.time() - start) * 1000.0

        # ── Phase 6: Build response ──────────────────────────────────────
        sources = [
            SourceNode.from_node(node, score=final_scores.get(node.id, 0.0))
            for node in final_nodes
            if node.id in reasoning_result.used_node_ids or True  # include all context nodes
        ]
        max_nodes = self.reasoner.config.max_context_nodes
        # Move cited nodes to top
        cited = set(reasoning_result.used_node_ids)
        sources.sort(key=lambda s: (s.node_id in cited, s.relevance_score), reverse=True)

        response = ContextResponse(
            question=question,
            answer=reasoning_result.answer,
            reasoning_trace=reasoning_result.reasoning_trace,
            sources=sources[:max_nodes],
            total_nodes_searched=len(candidates),
            confidence=reasoning_result.confidence,
            retrieval_method=f"semantic+graph(depth={graph_depth})",
            collection=self.graph.collection,
            model_used=reasoning_result.model_used,
            latency_ms=latency_ms,
        )

        # ── Phase 7: Emit telemetry ───────────────────────────────────────
        self._tracer.record_query(
            collection=self.graph.collection,
            question=question,
            nodes_retrieved=len(final_nodes),
            latency_ms=latency_ms,
            reasoning_summary=reasoning_result.reasoning_trace[:200],
            query_origin=query_origin,
        )

        # Log telemetry unless this is a maintenance query and verbose is disabled
        if query_origin != "maintenance" or self._verbose:
            logger.info(
                "Maintenance query answered" if query_origin == "maintenance" else "User query answered",
                collection=self.graph.collection,
                nodes_retrieved=len(final_nodes),
                confidence=reasoning_result.confidence,
                latency_ms=f"{latency_ms:.1f}",
                query_origin=query_origin,
                question=question[:120],
            )

        return response

    async def prepare_context(
        self,
        query: str,
        top_k: int = 15,
        threshold: float = 0.25,
        depth: int = 2,
        working_memory_boost: float = 0.15,
    ) -> tuple[list[MemoryNode], dict[str, float], list[tuple[MemoryNode, float]]]:
        """
        Runs the retrieval and re-ranking pipeline without reasoning.
        Returns (nodes_for_llm, score_map, all_candidates).
        """
        candidates = await self.graph.semantic_search_with_graph_expansion(
            query=query,
            top_k=top_k,
            threshold=threshold,
            depth=depth,
        )
        reranked = self._rerank(candidates, working_memory_boost)
        max_nodes = self.reasoner.config.max_context_nodes
        
        final_nodes = [node for node, _ in reranked[:max_nodes]]
        final_scores = {node.id: score for node, score in reranked[:max_nodes]}
        return final_nodes, final_scores, candidates

    async def retrieve_only(
        self,
        query: str,
        top_k: int = 10,
        threshold: float = 0.25,
        depth: int = 1,
    ) -> list[tuple[MemoryNode, float]]:
        """
        Pure retrieval without LLM reasoning.
        Useful when the calling agent wants to do its own reasoning.
        """
        candidates = await self.graph.semantic_search_with_graph_expansion(
            query=query,
            top_k=top_k,
            threshold=threshold,
            depth=depth,
        )
        for node, _ in candidates:
            self.agent.record_access(node.id)
        return candidates

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _rerank(
        self,
        candidates: list[tuple[MemoryNode, float]],
        working_boost: float,
    ) -> list[tuple[MemoryNode, float]]:
        """
        Re-rank candidates by applying bonuses:
        - Working memory nodes: +working_boost
        - Higher importance nodes: +0.05 bonus per 0.1 importance above 0.5
        """
        reranked = []
        for node, score in candidates:
            adjusted = score
            if node.tier == MemoryTier.WORKING:
                adjusted += working_boost
            if node.importance > 0.5:
                adjusted += (node.importance - 0.5) * 0.1
            reranked.append((node, adjusted))
        reranked.sort(key=lambda x: x[1], reverse=True)
        return reranked


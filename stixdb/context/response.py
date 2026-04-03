"""
ContextResponse — the structured output returned to external agents.

Every agentic query to StixDB returns a ContextResponse, never raw data.
It includes the answer, the reasoning trace, source nodes, and metadata
so the calling agent can make informed decisions about trust and relevance.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from pydantic import BaseModel, Field

from stixdb.graph.node import MemoryNode


class SourceNode(BaseModel):
    """A summarised view of a retrieved MemoryNode (no embedding)."""
    node_id: str
    content: str
    node_type: str
    tier: str
    importance: float
    relevance_score: float
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_node(cls, node: MemoryNode, score: float = 0.0) -> "SourceNode":
        return cls(
            node_id=node.id,
            content=node.content,
            node_type=node.node_type.value,
            tier=node.tier.value,
            importance=node.importance,
            relevance_score=score,
            metadata=node.metadata,
        )


class ContextResponse(BaseModel):
    """
    The primary output of a StixDB agentic query.
    
    External agents should use `answer` for their task,
    `reasoning_trace` for debugging/auditing,
    and `sources` for attribution / follow-up queries.
    """
    # Core answer
    question: str
    answer: Any
    reasoning_trace: str

    # Source attribution
    sources: list[SourceNode] = Field(default_factory=list)
    total_nodes_searched: int = 0

    # Quality signals
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    retrieval_method: str = "semantic+graph"   # for debugging

    # Backend metadata
    collection: str
    model_used: str = "none"
    latency_ms: float = 0.0
    timestamp: float = Field(default_factory=time.time)

    @property
    def is_confident(self) -> bool:
        return self.confidence >= 0.7

    def to_dict(self) -> dict:
        d = self.model_dump()
        return d

    def __repr__(self) -> str:
        return (
            f"ContextResponse(confidence={self.confidence:.2f}, "
            f"sources={len(self.sources)}, latency={self.latency_ms:.0f}ms)"
        )

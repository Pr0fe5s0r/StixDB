"""
RelationEdge — typed, directed relationship between two MemoryNodes.

Edges are first-class citizens in StixDB. They encode how a node
relates to others and are used by the agent to reason about context
and by the Context Broker for graph traversal.
"""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class RelationType(str, Enum):
    """
    Semantic relationship types between memory nodes.
    Deliberately limited to avoid ontology sprawl — agents can
    add custom types via the 'metadata' field.
    """
    # Causal / logical
    CAUSES = "causes"
    ENABLES = "enables"
    PREVENTS = "prevents"
    REQUIRES = "requires"

    # Evidential
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    WEAKENS = "weakens"

    # Structural
    PART_OF = "part_of"
    HAS_PART = "has_part"
    INSTANCE_OF = "instance_of"

    # Temporal
    PRECEDES = "precedes"
    FOLLOWS = "follows"
    CONCURRENT_WITH = "concurrent_with"

    # Semantic
    RELATES_TO = "relates_to"
    SIMILAR_TO = "similar_to"
    OPPOSITE_OF = "opposite_of"

    # Provenance (used by the consolidator)
    DERIVED_FROM = "derived_from"
    SUMMARIZES = "summarizes"
    REFERENCES = "references"

    # Agent-specific
    INFERRED_FROM = "inferred_from"   # Edge created by LLM reasoning
    TAGGED_WITH = "tagged_with"       # Node ↔ concept/tag node


class RelationEdge(BaseModel):
    """
    A directed, typed, weighted edge between two MemoryNodes.
    
    Edges are automatically created when:
    - The application explicitly adds them
    - The Memory Agent's consolidator detects semantic similarity
    - The Reasoner infers a logical relationship during reasoning
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    collection: str

    source_id: str = Field(..., description="ID of the source MemoryNode.")
    target_id: str = Field(..., description="ID of the target MemoryNode.")
    relation_type: RelationType = RelationType.RELATES_TO

    # Edge strength — influences graph traversal scoring
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="How confident the agent/system is in this relation."
    )

    created_at: float = Field(default_factory=time.time)
    created_by: Optional[str] = None  # 'system', 'agent', or external agent ID

    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_agent_inferred(self) -> bool:
        return self.created_by == "agent" or self.relation_type == RelationType.INFERRED_FROM

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RelationEdge":
        return cls(**data)

    def __repr__(self) -> str:
        return (
            f"RelationEdge({self.source_id[:8]}... "
            f"--[{self.relation_type.value}:{self.weight:.2f}]--> "
            f"{self.target_id[:8]}...)"
        )

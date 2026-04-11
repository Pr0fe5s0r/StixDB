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


class EdgeProvenance(str, Enum):
    """How this edge was established."""
    EXTRACTED  = "extracted"   # Found directly in source (AST, doc structure, explicit links)
    INFERRED   = "inferred"    # LLM-reasoned relationship — see confidence field
    AMBIGUOUS  = "ambiguous"   # Low-confidence inference, flagged for review


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

    # ── Pass 1: structural code edges (EXTRACTED) ─────────────────────────
    CALLS     = "calls"      # function/method invokes another
    IMPORTS   = "imports"    # module imports another module
    INHERITS  = "inherits"   # class inherits from another class
    DEFINES   = "defines"    # module/class defines a function or class
    MUTATES   = "mutates"    # function mutates state of another node

    # ── Pass 1: structural doc edges (EXTRACTED) ──────────────────────────
    SECTION_OF = "section_of"  # doc_section belongs to a doc_file
    LINKS_TO   = "links_to"    # hyperlink or explicit reference between doc nodes

    # ── Pass 2: semantic bridge edges (INFERRED) ──────────────────────────
    EXPLAINS    = "explains"    # one node clarifies or documents another
    MOTIVATES   = "motivates"   # one node is the reason another exists
    DECIDES     = "decides"     # decision node governs implementation node
    IMPLEMENTS  = "implements"  # code node realises a design/decision node
    VALIDATES   = "validates"   # test or doc node confirms another node's behaviour
    ABOUT       = "about"       # cross-media anchor: any node references a concept node
    SUPERSEDES  = "supersedes"  # this node replaces a previous node

    # ── Session edges ─────────────────────────────────────────────────────
    CHAT = "chat"  # links nodes created or discussed within the same conversation session


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
    provenance: EdgeProvenance = Field(
        default=EdgeProvenance.EXTRACTED,
        description="How this edge was established: extracted from source, inferred by LLM, or ambiguous."
    )
    rationale: Optional[str] = Field(
        default=None,
        description="LLM-provided explanation for INFERRED edges. None for EXTRACTED edges."
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

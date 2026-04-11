"""
MemoryNode — the atomic unit of memory in StixDB.

Every piece of data the engine manages is a MemoryNode.
Unlike rows or documents, nodes have rich lifecycle metadata so the
agent can make intelligent decisions about what to keep, merge, or prune.
"""
from __future__ import annotations

import math
import time
import uuid
from enum import Enum
from typing import Any, Optional

import numpy as np
from pydantic import BaseModel, Field


class NodeType(str, Enum):
    """The semantic role of a memory node."""
    FACT = "fact"               # Objective statement about the world
    ENTITY = "entity"           # A person, place, org, thing
    EVENT = "event"             # Something that happened at a point in time
    CONCEPT = "concept"         # An abstract idea or category — cross-media anchor for ABOUT edges
    PROCEDURE = "procedure"     # A how-to or step sequence
    SUMMARY = "summary"         # Auto-generated summary of merged nodes
    QUESTION = "question"       # An open query posed by an external agent

    # ── Code nodes (Pass 1 AST extraction) ───────────────────────────────
    CODE_FILE = "code_file"     # A source file on disk
    MODULE    = "module"        # A Python module (logical unit within a file)
    FUNCTION  = "function"      # A function or method definition
    CLASS     = "class"         # A class definition

    # ── Document nodes ────────────────────────────────────────────────────
    DOC_FILE    = "doc_file"    # A document file (.md, .pdf, .txt, etc.)
    DOC_SECTION = "doc_section" # A section or chunk within a document

    # ── Decision / session nodes ──────────────────────────────────────────
    DECISION     = "decision"     # A recorded architectural or design decision
    CONVERSATION = "conversation" # A session or dialogue — anchor for CHAT edges


class MemoryTier(str, Enum):
    """Which memory tier a node currently lives in."""
    WORKING = "working"         # Hot, actively accessed
    EPISODIC = "episodic"       # Timestamped events / recent context
    SEMANTIC = "semantic"       # Generalised knowledge
    PROCEDURAL = "procedural"   # Skills / how-to sequences
    ARCHIVED = "archived"       # Cold; eligible for deletion


class MemoryNode(BaseModel):
    """
    Atomic unit of memory in the StixDB graph.
    
    Lifecycle fields (access_count, last_accessed, decay_score, importance)
    are continuously updated by the Memory Agent's planner and consolidator.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    collection: str = Field(..., description="Which collection this node belongs to.")

    # --- Content ---
    content: str = Field(..., description="The raw text / data of this memory.")
    node_type: NodeType = NodeType.FACT
    tier: MemoryTier = MemoryTier.EPISODIC

    # --- Embedding (stored as list for JSON-serialisable persistence) ---
    embedding: Optional[list[float]] = Field(
        default=None,
        description="Vector embedding of the content. Set by the storage layer."
    )

    # --- Lifecycle / Decay ---
    access_count: int = 0
    created_at: float = Field(default_factory=time.time)
    last_accessed: float = Field(default_factory=time.time)
    importance: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="Agent-assigned importance score. Influences tier promotion and pruning."
    )
    decay_score: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="Current vitality of this node. Decays over time, boosted on access."
    )

    # --- Source Provenance ---
    source: Optional[str] = None
    source_agent_id: Optional[str] = None
    parent_node_ids: list[str] = Field(
        default_factory=list,
        description="If this is a SUMMARY node, lists the IDs of merged source nodes."
    )

    # --- Metadata (arbitrary key-value for application use) ---
    metadata: dict[str, Any] = Field(default_factory=dict)

    # --- Agent Reasoning Anchors ---
    tags: list[str] = Field(default_factory=list)
    pinned: bool = True  # Pinned nodes are never pruned

    class Config:
        # Allow mutation so the agent can update lifecycle fields in place
        validate_assignment = True

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def touch(self) -> None:
        """Record an access event — updates access_count, last_accessed, and decay_score."""
        self.access_count += 1
        self.last_accessed = time.time()
        # Boost decay score by 20%, capped at 1.0
        self.decay_score = min(1.0, self.decay_score * 1.2 + 0.1)

    def compute_decay(self, half_life_hours: float = 48.0) -> float:
        """
        Compute and update the decay score using exponential decay.
        
        Formula: score = importance * 2^(-elapsed_hours / half_life)
        Returns: Updated decay_score
        """
        elapsed_hours = (time.time() - self.last_accessed) / 3600.0
        self.decay_score = self.importance * math.pow(
            2.0, -(elapsed_hours / half_life_hours)
        )
        return self.decay_score

    def get_embedding_array(self) -> Optional[np.ndarray]:
        """Return embedding as a numpy array, or None if not yet set."""
        if self.embedding is None:
            return None
        return np.array(self.embedding, dtype=np.float32)

    def set_embedding(self, vec: np.ndarray) -> None:
        """Store numpy embedding as a JSON-serialisable list."""
        self.embedding = vec.tolist()

    def promote_tier(self, new_tier: MemoryTier) -> None:
        """Promote or demote this node to the given memory tier."""
        self.tier = new_tier

    def to_dict(self, include_embedding: bool = False) -> dict[str, Any]:
        """Serialise to a plain dict. Optionally omit the embedding vector."""
        d = self.model_dump()
        if not include_embedding:
            d.pop("embedding", None)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryNode":
        return cls(**data)

    def __repr__(self) -> str:
        return (
            f"MemoryNode(id={self.id[:8]}..., type={self.node_type.value}, "
            f"tier={self.tier.value}, importance={self.importance:.2f}, "
            f"access={self.access_count}, content={self.content[:60]!r})"
        )

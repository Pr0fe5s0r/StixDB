"""
MemoryCluster — a group of semantically related MemoryNodes.

Clusters are the agent's view of the world: it continuously groups
nodes into clusters and uses them for efficient retrieval and
context building. The four cluster types mirror cognitive memory theory.
"""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ClusterType(str, Enum):
    WORKING = "working"         # Hot, recently / frequently accessed nodes
    EPISODIC = "episodic"       # Timestamped events and contextual sessions
    SEMANTIC = "semantic"       # Generalised, distilled knowledge
    PROCEDURAL = "procedural"   # How-to sequences and processes
    CUSTOM = "custom"           # Application-defined clusters


class MemoryCluster(BaseModel):
    """
    A named group of MemoryNode IDs maintained by the Memory Agent.
    
    The agent creates and updates clusters autonomously as it observes
    access patterns and semantic relationships. Applications can also
    create custom clusters for domain-specific organisation.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    collection: str
    name: str
    cluster_type: ClusterType = ClusterType.SEMANTIC

    node_ids: list[str] = Field(default_factory=list)

    summary: Optional[str] = None  # Agent-generated textual summary of this cluster
    centroid_embedding: Optional[list[float]] = None  # Mean embedding of member nodes

    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    access_count: int = 0

    metadata: dict[str, Any] = Field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # Membership management                                                #
    # ------------------------------------------------------------------ #

    def add_node(self, node_id: str) -> None:
        if node_id not in self.node_ids:
            self.node_ids.append(node_id)
            self.updated_at = time.time()

    def remove_node(self, node_id: str) -> None:
        if node_id in self.node_ids:
            self.node_ids.remove(node_id)
            self.updated_at = time.time()

    def touch(self) -> None:
        self.access_count += 1

    @property
    def size(self) -> int:
        return len(self.node_ids)

    @property
    def is_empty(self) -> bool:
        return len(self.node_ids) == 0

    def to_dict(self, include_centroid: bool = False) -> dict[str, Any]:
        d = self.model_dump()
        if not include_centroid:
            d.pop("centroid_embedding", None)
        return d

    def __repr__(self) -> str:
        return (
            f"MemoryCluster(name={self.name!r}, type={self.cluster_type.value}, "
            f"nodes={self.size}, updated={self.updated_at:.0f})"
        )

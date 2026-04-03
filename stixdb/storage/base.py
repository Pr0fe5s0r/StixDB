"""
Abstract StorageBackend interface.
All storage backends (NetworkX, future Neo4j) must implement this contract.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from stixdb.graph.node import MemoryNode
from stixdb.graph.edge import RelationEdge
from stixdb.graph.cluster import MemoryCluster


class StorageBackend(ABC):
    """
    Abstract base class for all StixDB storage backends.
    
    Each backend must support atomic node/edge CRUD, cluster management,
    and basic graph traversal. Vector/semantic search is handled separately
    by the VectorStore layer.
    """

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def initialize(self, collection: str) -> None:
        """Initialise storage for a new collection. Idempotent."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Gracefully close connections and flush pending writes."""
        ...

    @abstractmethod
    async def list_collections(self) -> list[str]:
        """Return all known collections for this backend."""
        ...

    @abstractmethod
    async def delete_collection(self, collection: str) -> bool:
        """Delete all data for a collection. Returns True if data was removed."""
        ...

    # ------------------------------------------------------------------ #
    # Nodes                                                                #
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def upsert_node(self, node: MemoryNode) -> None:
        """Insert or update a MemoryNode atomically."""
        ...

    @abstractmethod
    async def get_node(self, node_id: str, collection: str) -> Optional[MemoryNode]:
        """Retrieve a node by ID. Returns None if not found."""
        ...

    async def get_nodes(self, node_ids: list[str], collection: str) -> list[MemoryNode]:
        """Retrieve multiple nodes by ID."""
        nodes: list[MemoryNode] = []
        for node_id in node_ids:
            node = await self.get_node(node_id, collection)
            if node is not None:
                nodes.append(node)
        return nodes

    @abstractmethod
    async def delete_node(self, node_id: str, collection: str) -> bool:
        """Delete a node and all its edges. Returns True if deleted."""
        ...

    @abstractmethod
    async def list_nodes(
        self,
        collection: str,
        tier: Optional[str] = None,
        node_type: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[MemoryNode]:
        """List nodes in a collection with optional filters."""
        ...

    @abstractmethod
    async def count_nodes(self, collection: str) -> int:
        """Return total node count for a collection."""
        ...

    # ------------------------------------------------------------------ #
    # Edges                                                                #
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def upsert_edge(self, edge: RelationEdge) -> None:
        """Insert or update a RelationEdge atomically."""
        ...

    @abstractmethod
    async def get_edge(self, edge_id: str, collection: str) -> Optional[RelationEdge]:
        """Retrieve an edge by ID."""
        ...

    @abstractmethod
    async def delete_edge(self, edge_id: str, collection: str) -> bool:
        """Delete a single edge. Returns True if deleted."""
        ...

    @abstractmethod
    async def get_neighbours(
        self,
        node_id: str,
        collection: str,
        direction: str = "both",      # "in", "out", "both"
        relation_types: Optional[list[str]] = None,
        max_depth: int = 1,
    ) -> list[MemoryNode]:
        """BFS neighbour traversal up to max_depth."""
        ...

    async def get_neighbours_for_nodes(
        self,
        node_ids: list[str],
        collection: str,
        direction: str = "both",
        relation_types: Optional[list[str]] = None,
        max_depth: int = 1,
    ) -> dict[str, list[MemoryNode]]:
        """Retrieve neighbours for multiple start nodes."""
        result: dict[str, list[MemoryNode]] = {}
        for node_id in node_ids:
            result[node_id] = await self.get_neighbours(
                node_id=node_id,
                collection=collection,
                direction=direction,
                relation_types=relation_types,
                max_depth=max_depth,
            )
        return result

    @abstractmethod
    async def get_edges_for_node(
        self,
        node_id: str,
        collection: str,
        direction: str = "both",
    ) -> list[RelationEdge]:
        """Return all edges connected to a given node."""
        ...

    # ------------------------------------------------------------------ #
    # Clusters                                                             #
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def upsert_cluster(self, cluster: MemoryCluster) -> None:
        """Insert or update a MemoryCluster."""
        ...

    @abstractmethod
    async def get_cluster(self, cluster_id: str, collection: str) -> Optional[MemoryCluster]:
        """Retrieve a cluster by ID."""
        ...

    @abstractmethod
    async def list_clusters(self, collection: str) -> list[MemoryCluster]:
        """List all clusters for a collection."""
        ...

    @abstractmethod
    async def delete_cluster(self, cluster_id: str, collection: str) -> bool:
        """Delete a cluster (not its member nodes)."""
        ...

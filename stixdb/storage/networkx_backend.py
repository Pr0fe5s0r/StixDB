"""
NetworkX in-memory storage backend.

Zero external dependencies — ideal for development, testing, and
embedding StixDB inside another process without infrastructure.
All data is lost on process exit. Use KuzuBackend for persistence.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from typing import Optional

import networkx as nx

from stixdb.storage.base import StorageBackend
from stixdb.graph.node import MemoryNode
from stixdb.graph.edge import RelationEdge
from stixdb.graph.cluster import MemoryCluster


class NetworkXBackend(StorageBackend):
    """
    Thread-safe, async-compatible, fully in-memory graph storage
    built on NetworkX MultiDiGraph.
    
    Each collection is an isolated graph instance.
    """

    def __init__(self) -> None:
        # collection -> nx.MultiDiGraph
        self._graphs: dict[str, nx.MultiDiGraph] = {}
        # collection -> {node_id: MemoryNode}
        self._nodes: dict[str, dict[str, MemoryNode]] = defaultdict(dict)
        # collection -> {edge_id: RelationEdge}
        self._edges: dict[str, dict[str, RelationEdge]] = defaultdict(dict)
        # collection -> {cluster_id: MemoryCluster}
        self._clusters: dict[str, dict[str, MemoryCluster]] = defaultdict(dict)
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def initialize(self, collection: str) -> None:
        async with self._lock:
            if collection not in self._graphs:
                self._graphs[collection] = nx.MultiDiGraph()

    async def close(self) -> None:
        pass  # In-memory — nothing to flush

    async def list_collections(self) -> list[str]:
        return list(self._graphs.keys())

    async def delete_collection(self, collection: str) -> bool:
        async with self._lock:
            removed = False
            if collection in self._graphs:
                del self._graphs[collection]
                removed = True
            if collection in self._nodes:
                del self._nodes[collection]
                removed = True
            if collection in self._edges:
                del self._edges[collection]
                removed = True
            if collection in self._clusters:
                del self._clusters[collection]
                removed = True
            return removed

    # ------------------------------------------------------------------ #
    # Nodes                                                                #
    # ------------------------------------------------------------------ #

    async def upsert_node(self, node: MemoryNode) -> None:
        async with self._lock:
            self._nodes[node.collection][node.id] = node
            self._graphs[node.collection].add_node(node.id)

    async def get_node(self, node_id: str, collection: str) -> Optional[MemoryNode]:
        return self._nodes[collection].get(node_id)

    async def get_nodes(self, node_ids: list[str], collection: str) -> list[MemoryNode]:
        return [
            node
            for node_id in node_ids
            if (node := self._nodes[collection].get(node_id)) is not None
        ]

    async def delete_node(self, node_id: str, collection: str) -> bool:
        async with self._lock:
            if node_id not in self._nodes[collection]:
                return False
            del self._nodes[collection][node_id]
            # Remove all edges for this node
            stale = [
                eid for eid, e in self._edges[collection].items()
                if e.source_id == node_id or e.target_id == node_id
            ]
            for eid in stale:
                del self._edges[collection][eid]
            if self._graphs[collection].has_node(node_id):
                self._graphs[collection].remove_node(node_id)
            return True

    async def list_nodes(
        self,
        collection: str,
        tier: Optional[str] = None,
        node_type: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
        include_embedding: bool = False,
    ) -> list[MemoryNode]:
        nodes = list(self._nodes[collection].values())
        if tier:
            nodes = [n for n in nodes if n.tier.value == tier]
        if node_type:
            nodes = [n for n in nodes if n.node_type.value == node_type]
        return nodes[offset : offset + limit]

    async def count_nodes(self, collection: str) -> int:
        return len(self._nodes[collection])

    # ------------------------------------------------------------------ #
    # Edges                                                                #
    # ------------------------------------------------------------------ #

    async def upsert_edge(self, edge: RelationEdge) -> None:
        async with self._lock:
            self._edges[edge.collection][edge.id] = edge
            g = self._graphs[edge.collection]
            g.add_edge(
                edge.source_id,
                edge.target_id,
                key=edge.id,
                relation_type=edge.relation_type.value,
                weight=edge.weight,
            )

    async def get_edge(self, edge_id: str, collection: str) -> Optional[RelationEdge]:
        return self._edges[collection].get(edge_id)

    async def delete_edge(self, edge_id: str, collection: str) -> bool:
        async with self._lock:
            edge = self._edges[collection].get(edge_id)
            if not edge:
                return False
            del self._edges[collection][edge_id]
            g = self._graphs[collection]
            if g.has_edge(edge.source_id, edge.target_id, key=edge_id):
                g.remove_edge(edge.source_id, edge.target_id, key=edge_id)
            return True

    async def get_neighbours(
        self,
        node_id: str,
        collection: str,
        direction: str = "both",
        relation_types: Optional[list[str]] = None,
        max_depth: int = 1,
    ) -> list[MemoryNode]:
        """BFS over the NetworkX graph up to max_depth."""
        g = self._graphs.get(collection)
        if g is None or node_id not in g:
            return []

        visited: set[str] = {node_id}
        queue: deque[tuple[str, int]] = deque([(node_id, 0)])
        result: list[MemoryNode] = []

        while queue:
            current_id, depth = queue.popleft()
            if depth >= max_depth:
                continue

            # Determine which edges to traverse
            if direction in ("out", "both"):
                for _, nbr, data in g.out_edges(current_id, data=True):
                    if relation_types and data.get("relation_type") not in relation_types:
                        continue
                    if nbr not in visited:
                        visited.add(nbr)
                        queue.append((nbr, depth + 1))
                        node = self._nodes[collection].get(nbr)
                        if node:
                            result.append(node)

            if direction in ("in", "both"):
                for nbr, _, data in g.in_edges(current_id, data=True):
                    if relation_types and data.get("relation_type") not in relation_types:
                        continue
                    if nbr not in visited:
                        visited.add(nbr)
                        queue.append((nbr, depth + 1))
                        node = self._nodes[collection].get(nbr)
                        if node:
                            result.append(node)

        return result

    async def get_neighbours_for_nodes(
        self,
        node_ids: list[str],
        collection: str,
        direction: str = "both",
        relation_types: Optional[list[str]] = None,
        max_depth: int = 1,
    ) -> dict[str, list[MemoryNode]]:
        grouped: dict[str, list[MemoryNode]] = {}
        for node_id in node_ids:
            grouped[node_id] = await self.get_neighbours(
                node_id=node_id,
                collection=collection,
                direction=direction,
                relation_types=relation_types,
                max_depth=max_depth,
            )
        return grouped

    async def get_edges_for_node(
        self,
        node_id: str,
        collection: str,
        direction: str = "both",
    ) -> list[RelationEdge]:
        edges = list(self._edges[collection].values())
        result = []
        for e in edges:
            if direction in ("out", "both") and e.source_id == node_id:
                result.append(e)
            elif direction in ("in", "both") and e.target_id == node_id:
                result.append(e)
        return result

    async def list_edges(self, collection: str) -> list[RelationEdge]:
        return list(self._edges[collection].values())

    # ------------------------------------------------------------------ #
    # Clusters                                                             #
    # ------------------------------------------------------------------ #

    async def upsert_cluster(self, cluster: MemoryCluster) -> None:
        async with self._lock:
            self._clusters[cluster.collection][cluster.id] = cluster

    async def get_cluster(self, cluster_id: str, collection: str) -> Optional[MemoryCluster]:
        return self._clusters[collection].get(cluster_id)

    async def list_clusters(self, collection: str) -> list[MemoryCluster]:
        return list(self._clusters[collection].values())

    async def delete_cluster(self, cluster_id: str, collection: str) -> bool:
        async with self._lock:
            if cluster_id not in self._clusters[collection]:
                return False
            del self._clusters[collection][cluster_id]
            return True

    # ------------------------------------------------------------------ #
    # Diagnostic helpers                                                   #
    # ------------------------------------------------------------------ #

    def get_graph(self, collection: str) -> Optional[nx.MultiDiGraph]:
        return self._graphs.get(collection)

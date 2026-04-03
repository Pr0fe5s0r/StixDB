"""
Neo4j persistent storage backend.

This backend uses a Neo4j graph database to persist memory nodes and relations.
It requires the 'neo4j' package:

    pip install neo4j
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Optional, Any

from stixdb.storage.base import StorageBackend
from stixdb.graph.node import MemoryNode, NodeType, MemoryTier
from stixdb.graph.edge import RelationEdge, RelationType
from stixdb.graph.cluster import MemoryCluster


class Neo4jBackend(StorageBackend):
    """
    Production-grade graph storage backed by Neo4j.
    """

    def __init__(self, uri: str, user: str, password: str) -> None:
        self.uri = uri
        self.user = user
        self.password = password
        self._driver: Any = None
        self._lock = asyncio.Lock()
        self._clusters: dict[str, dict[str, MemoryCluster]] = {}

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def initialize(self, collection: str) -> None:
        try:
            from neo4j import GraphDatabase, AsyncGraphDatabase
        except ImportError:
            raise ImportError(
                "Neo4j driver is not installed. Run: pip install neo4j"
            )

        async with self._lock:
            if self._driver is None:
                self._driver = AsyncGraphDatabase.driver(
                    self.uri, auth=(self.user, self.password)
                )
            
            if collection not in self._clusters:
                self._clusters[collection] = {}

            # Create constraints idempotently
            async with self._driver.session() as session:
                await session.run(
                    "CREATE CONSTRAINT IF NOT EXISTS FOR (n:MemoryNode) REQUIRE n.id IS UNIQUE"
                )
                await session.run(
                    "CREATE INDEX IF NOT EXISTS FOR (n:MemoryNode) ON (n.collection)"
                )

    async def close(self) -> None:
        async with self._lock:
            if self._driver:
                await self._driver.close()
                self._driver = None

    async def list_collections(self) -> list[str]:
        if self._driver is None:
            try:
                from neo4j import AsyncGraphDatabase
            except ImportError:
                raise ImportError(
                    "Neo4j driver is not installed. Run: pip install neo4j"
                )
            self._driver = AsyncGraphDatabase.driver(
                self.uri, auth=(self.user, self.password)
            )

        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (n:MemoryNode)
                WHERE n.collection IS NOT NULL AND n.collection <> ""
                RETURN DISTINCT n.collection AS collection
                ORDER BY collection
                """
            )
            collections = []
            async for record in result:
                collections.append(record["collection"])
            return collections

    async def delete_collection(self, collection: str) -> bool:
        async with self._driver.session() as session:
            count_result = await session.run(
                """
                MATCH (n:MemoryNode {collection: $collection})
                RETURN count(n) AS count
                """,
                {"collection": collection},
            )
            record = await count_result.single()
            count = record["count"] if record else 0
            if count:
                delete_result = await session.run(
                    "MATCH (n:MemoryNode {collection: $collection}) DETACH DELETE n",
                    {"collection": collection},
                )
                await delete_result.consume()
            self._clusters.pop(collection, None)
            return bool(count)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _node_to_params(self, node: MemoryNode) -> dict:
        return {
            "id": node.id,
            "collection": node.collection,
            "content": node.content,
            "node_type": node.node_type.value,
            "tier": node.tier.value,
            "embedding": json.dumps(node.embedding) if node.embedding else None,
            "access_count": node.access_count,
            "created_at": node.created_at,
            "last_accessed": node.last_accessed,
            "importance": node.importance,
            "decay_score": node.decay_score,
            "source": node.source or "",
            "source_agent_id": node.source_agent_id or "",
            "parent_node_ids": json.dumps(node.parent_node_ids),
            "metadata": json.dumps(node.metadata),
            "tags": json.dumps(node.tags),
            "pinned": node.pinned,
        }

    def _record_to_node(self, record: Any) -> MemoryNode:
        n = record["n"]
        embedding = json.loads(n["embedding"]) if n.get("embedding") else None
        return MemoryNode(
            id=n["id"],
            collection=n["collection"],
            content=n["content"],
            node_type=NodeType(n["node_type"]),
            tier=MemoryTier(n["tier"]),
            embedding=embedding,
            access_count=n["access_count"],
            created_at=n["created_at"],
            last_accessed=n["last_accessed"],
            importance=n["importance"],
            decay_score=n["decay_score"],
            source=n.get("source") or None,
            source_agent_id=n.get("source_agent_id") or None,
            parent_node_ids=json.loads(n.get("parent_node_ids", "[]")),
            metadata=json.loads(n.get("metadata", "{}")),
            tags=json.loads(n.get("tags", "[]")),
            pinned=n.get("pinned", False),
        )

    # ------------------------------------------------------------------ #
    # Nodes                                                                #
    # ------------------------------------------------------------------ #

    async def upsert_node(self, node: MemoryNode) -> None:
        async with self._driver.session() as session:
            params = self._node_to_params(node)
            await session.run(
                """
                MERGE (n:MemoryNode {id: $id})
                SET n += $params
                """,
                {"id": node.id, "params": params}
            )

    async def get_node(self, node_id: str, collection: str) -> Optional[MemoryNode]:
        async with self._driver.session() as session:
            result = await session.run(
                "MATCH (n:MemoryNode {id: $id, collection: $collection}) RETURN n",
                {"id": node_id, "collection": collection}
            )
            record = await result.single()
            if record:
                return self._record_to_node(record)
            return None

    async def get_nodes(self, node_ids: list[str], collection: str) -> list[MemoryNode]:
        if not node_ids:
            return []

        async with self._driver.session() as session:
            result = await session.run(
                """
                UNWIND $ids AS node_id
                MATCH (n:MemoryNode {id: node_id, collection: $collection})
                RETURN n
                """,
                {"ids": node_ids, "collection": collection},
            )
            nodes: list[MemoryNode] = []
            async for record in result:
                nodes.append(self._record_to_node(record))
            return nodes

    async def delete_node(self, node_id: str, collection: str) -> bool:
        async with self._driver.session() as session:
            await session.run(
                "MATCH (n:MemoryNode {id: $id, collection: $collection}) DETACH DELETE n",
                {"id": node_id, "collection": collection}
            )
            return True

    async def list_nodes(
        self,
        collection: str,
        tier: Optional[str] = None,
        node_type: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[MemoryNode]:
        async with self._driver.session() as session:
            query = "MATCH (n:MemoryNode {collection: $collection})"
            params = {"collection": collection, "limit": limit, "offset": offset}
            
            where_clauses = []
            if tier:
                where_clauses.append("n.tier = $tier")
                params["tier"] = tier
            if node_type:
                where_clauses.append("n.node_type = $node_type")
                params["node_type"] = node_type
                
            if where_clauses:
                query += " WHERE " + " AND ".join(where_clauses)
                
            query += " RETURN n SKIP $offset LIMIT $limit"
            
            result = await session.run(query, params)
            nodes = []
            async for record in result:
                nodes.append(self._record_to_node(record))
            return nodes

    async def count_nodes(self, collection: str) -> int:
        async with self._driver.session() as session:
            result = await session.run(
                "MATCH (n:MemoryNode {collection: $collection}) RETURN count(n) AS count",
                {"collection": collection}
            )
            record = await result.single()
            return record["count"] if record else 0

    # ------------------------------------------------------------------ #
    # Edges                                                                #
    # ------------------------------------------------------------------ #

    async def upsert_edge(self, edge: RelationEdge) -> None:
        async with self._driver.session() as session:
            await session.run(
                """
                MATCH (src:MemoryNode {id: $src_id}), (tgt:MemoryNode {id: $tgt_id})
                MERGE (src)-[r:Relation {id: $id}]->(tgt)
                SET r.collection = $collection,
                    r.relation_type = $relation_type,
                    r.weight = $weight,
                    r.confidence = $confidence,
                    r.created_at = $created_at,
                    r.created_by = $created_by,
                    r.metadata = $metadata
                """,
                {
                    "id": edge.id,
                    "src_id": edge.source_id,
                    "tgt_id": edge.target_id,
                    "collection": edge.collection,
                    "relation_type": edge.relation_type.value,
                    "weight": edge.weight,
                    "confidence": edge.confidence,
                    "created_at": edge.created_at,
                    "created_by": edge.created_by or "system",
                    "metadata": json.dumps(edge.metadata),
                }
            )

    async def get_edge(self, edge_id: str, collection: str) -> Optional[RelationEdge]:
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (src)-[r:Relation {id: $id, collection: $collection}]->(tgt)
                RETURN r, src.id AS src_id, tgt.id AS tgt_id
                """,
                {"id": edge_id, "collection": collection}
            )
            record = await result.single()
            if record:
                r = record["r"]
                return RelationEdge(
                    id=r["id"],
                    collection=collection,
                    source_id=record["src_id"],
                    target_id=record["tgt_id"],
                    relation_type=RelationType(r["relation_type"]),
                    weight=r["weight"],
                    confidence=r["confidence"],
                    created_at=r["created_at"],
                    created_by=r["created_by"],
                    metadata=json.loads(r.get("metadata", "{}")),
                )
            return None

    async def delete_edge(self, edge_id: str, collection: str) -> bool:
        async with self._driver.session() as session:
            await session.run(
                "MATCH ()-[r:Relation {id: $id, collection: $collection}]->() DELETE r",
                {"id": edge_id, "collection": collection}
            )
            return True

    async def get_neighbours(
        self,
        node_id: str,
        collection: str,
        direction: str = "both",
        relation_types: Optional[list[str]] = None,
        max_depth: int = 1,
    ) -> list[MemoryNode]:
        async with self._driver.session() as session:
            rel_filter = ""
            if relation_types:
                rel_filter = ":" + "|".join(relation_types)

            if direction == "out":
                pattern = f"(start)-[r{rel_filter}*1..{max_depth}]->(n)"
            elif direction == "in":
                pattern = f"(start)<-[r{rel_filter}*1..{max_depth}]-(n)"
            else:
                pattern = f"(start)-[r{rel_filter}*1..{max_depth}]-(n)"

            query = f"MATCH (start:MemoryNode {{id: $id, collection: $collection}}) MATCH {pattern} WHERE n.id <> $id RETURN n"
            
            result = await session.run(query, {"id": node_id, "collection": collection})
            nodes = []
            async for record in result:
                nodes.append(self._record_to_node(record))
            return nodes

    async def get_neighbours_for_nodes(
        self,
        node_ids: list[str],
        collection: str,
        direction: str = "both",
        relation_types: Optional[list[str]] = None,
        max_depth: int = 1,
    ) -> dict[str, list[MemoryNode]]:
        if not node_ids:
            return {}

        async with self._driver.session() as session:
            rel_filter = ""
            if relation_types:
                rel_filter = ":" + "|".join(relation_types)

            if direction == "out":
                pattern = f"(start)-[r{rel_filter}*1..{max_depth}]->(n)"
            elif direction == "in":
                pattern = f"(start)<-[r{rel_filter}*1..{max_depth}]-(n)"
            else:
                pattern = f"(start)-[r{rel_filter}*1..{max_depth}]-(n)"

            query = f"""
                UNWIND $ids AS start_id
                MATCH (start:MemoryNode {{id: start_id, collection: $collection}})
                MATCH {pattern}
                WHERE n.id <> start_id AND n.collection = $collection
                RETURN start_id, n
            """

            result = await session.run(
                query,
                {"ids": node_ids, "collection": collection},
            )
            grouped: dict[str, list[MemoryNode]] = {node_id: [] for node_id in node_ids}
            seen_pairs: set[tuple[str, str]] = set()
            async for record in result:
                start_id = record["start_id"]
                node = self._record_to_node(record)
                pair = (start_id, node.id)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                grouped.setdefault(start_id, []).append(node)
            return grouped

    async def get_edges_for_node(
        self,
        node_id: str,
        collection: str,
        direction: str = "both",
    ) -> list[RelationEdge]:
        async with self._driver.session() as session:
            if direction == "out":
                pattern = "(n)-[r:Relation]->(m)"
            elif direction == "in":
                pattern = "(n)<-[r:Relation]-(m)"
            else:
                pattern = "(n)-[r:Relation]-(m)"

            query = f"MATCH (n:MemoryNode {{id: $id, collection: $collection}}) MATCH {pattern} RETURN r, startNode(r).id AS src_id, endNode(r).id AS tgt_id"
            
            result = await session.run(query, {"id": node_id, "collection": collection})
            edges = []
            async for record in result:
                r = record["r"]
                edges.append(RelationEdge(
                    id=r["id"],
                    collection=collection,
                    source_id=record["src_id"],
                    target_id=record["tgt_id"],
                    relation_type=RelationType(r["relation_type"]),
                    weight=r["weight"],
                    confidence=r["confidence"],
                    created_at=r["created_at"],
                    created_by=r.get("created_by"),
                    metadata=json.loads(r.get("metadata") or "{}"),
                ))
            return edges

    # ------------------------------------------------------------------ #
    # Clusters                                                             #
    # ------------------------------------------------------------------ #

    async def upsert_cluster(self, cluster: MemoryCluster) -> None:
        if cluster.collection not in self._clusters:
            self._clusters[cluster.collection] = {}
        self._clusters[cluster.collection][cluster.id] = cluster

    async def get_cluster(self, cluster_id: str, collection: str) -> Optional[MemoryCluster]:
        return self._clusters.get(collection, {}).get(cluster_id)

    async def list_clusters(self, collection: str) -> list[MemoryCluster]:
        return list(self._clusters.get(collection, {}).values())

    async def delete_cluster(self, cluster_id: str, collection: str) -> bool:
        col = self._clusters.get(collection, {})
        if cluster_id in col:
            del col[cluster_id]
            return True
        return False

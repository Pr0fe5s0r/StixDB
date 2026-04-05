"""
KuzuDB embedded graph storage backend.

  * Fully persistent on disk — survives process restarts.
  * Zero external services — no Docker, no Neo4j, no Postgres.
  * Ideal for local development and single-machine deployments.
  * Implements the same StorageBackend contract as NetworkXBackend.

Usage:
    from stixdb.storage.kuzu_backend import KuzuBackend
    backend = KuzuBackend(db_path="./stixdb_data/kuzu")

Schema (created automatically on first run):
    Node table   : MemoryNode   (id, collection, …all MemoryNode fields…)
    Rel  table   : RelationEdge (id, collection, …)
    Node table   : MemoryCluster (id, collection, …)
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import Optional

import structlog

from stixdb.storage.base import StorageBackend
from stixdb.graph.node import MemoryNode, NodeType, MemoryTier
from stixdb.graph.edge import RelationEdge, RelationType
from stixdb.graph.cluster import MemoryCluster, ClusterType

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# DDL helpers
# ---------------------------------------------------------------------------

_DDL_MEMORY_NODE = """
CREATE NODE TABLE IF NOT EXISTS MemoryNode (
    id          STRING,
    collection  STRING,
    content     STRING,
    node_type   STRING,
    tier        STRING,
    importance  DOUBLE,
    source      STRING,
    source_agent_id STRING,
    tags        STRING,
    metadata    STRING,
    embedding   STRING,
    parent_node_ids STRING,
    pinned      BOOLEAN,
    created_at  DOUBLE,
    updated_at  DOUBLE,
    last_accessed DOUBLE,
    access_count INT64,
    PRIMARY KEY (id)
)
"""

_DDL_RELATION_EDGE = """
CREATE REL TABLE IF NOT EXISTS RelationEdge (
    FROM MemoryNode TO MemoryNode,
    id          STRING,
    collection  STRING,
    relation_type STRING,
    weight      DOUBLE,
    confidence  DOUBLE,
    created_by  STRING,
    metadata    STRING,
    created_at  DOUBLE
)
"""

_DDL_MEMORY_CLUSTER = """
CREATE NODE TABLE IF NOT EXISTS MemoryCluster (
    id          STRING,
    collection  STRING,
    label       STRING,
    cluster_type STRING,
    member_ids  STRING,
    summary     STRING,
    tags        STRING,
    metadata    STRING,
    created_at  DOUBLE,
    updated_at  DOUBLE,
    PRIMARY KEY (id)
)
"""


def _encode_embedding(embedding_data: list) -> str:
    """Encode embedding as base64 binary (float32). ~4.5x smaller than JSON text."""
    if not embedding_data:
        return ""
    import numpy as np
    arr = np.array(embedding_data, dtype="float32")
    return base64.b64encode(arr.tobytes()).decode("ascii")


def _decode_embedding(raw: str):
    """Decode embedding — handles base64 binary (new) and JSON text (legacy)."""
    if not raw:
        return None
    import numpy as np
    # Try base64 binary first (new format)
    try:
        arr = np.frombuffer(base64.b64decode(raw.encode("ascii")), dtype="float32").copy()
        if arr.size > 0:
            return arr
    except Exception:
        pass
    # Fallback: legacy JSON text format
    try:
        data = json.loads(raw)
        if data:
            return np.array(data, dtype="float32")
    except Exception:
        pass
    return None


def _node_to_row(node: MemoryNode) -> dict:
    # Handle embedding: could be list or numpy array
    embedding_data = []
    if node.embedding is not None:
        if isinstance(node.embedding, list):
            embedding_data = node.embedding
        else:
            # Assume it's a numpy array
            embedding_data = node.embedding.tolist()

    return {
        "id": node.id,
        "collection": node.collection,
        "content": node.content,
        "node_type": node.node_type.value,
        "tier": node.tier.value,
        "importance": float(node.importance),
        "source": node.source or "",
        "source_agent_id": node.source_agent_id or "",
        "tags": json.dumps(node.tags or []),
        "metadata": json.dumps(node.metadata or {}),
        "embedding": _encode_embedding(embedding_data),
        "parent_node_ids": json.dumps(node.parent_node_ids or []),
        "pinned": bool(node.pinned),
        "created_at": float(node.created_at),
        "updated_at": float(node.last_accessed),  # Use last_accessed as updated_at since MemoryNode doesn't have updated_at
        "last_accessed": float(node.last_accessed),
        "access_count": int(node.access_count),
    }


def _row_to_node(row: dict) -> MemoryNode:
    embedding = _decode_embedding(row.get("embedding") or "")
    return MemoryNode(
        id=row["id"],
        collection=row["collection"],
        content=row["content"],
        node_type=NodeType(row["node_type"]),
        tier=MemoryTier(row["tier"]),
        importance=float(row.get("importance", 0.5)),
        source=row.get("source") or None,
        source_agent_id=row.get("source_agent_id") or None,
        tags=json.loads(row.get("tags") or "[]"),
        metadata=json.loads(row.get("metadata") or "{}"),
        embedding=embedding,
        parent_node_ids=json.loads(row.get("parent_node_ids") or "[]"),
        pinned=bool(row.get("pinned", False)),
        created_at=float(row.get("created_at", 0.0)),
        updated_at=float(row.get("updated_at", 0.0)),
        last_accessed=float(row.get("last_accessed", 0.0)),
        access_count=int(row.get("access_count", 0)),
    )


def _edge_to_row(edge: RelationEdge) -> dict:
    return {
        "id": edge.id,
        "collection": edge.collection,
        "source_id": edge.source_id,
        "target_id": edge.target_id,
        "relation_type": edge.relation_type.value,
        "weight": float(edge.weight),
        "confidence": float(edge.confidence),
        "created_by": edge.created_by or "system",
        "metadata": json.dumps(edge.metadata or {}),
        "created_at": float(edge.created_at),
    }


def _row_to_edge(row: dict) -> RelationEdge:
    return RelationEdge(
        id=row["id"],
        collection=row["collection"],
        source_id=row["source_id"],
        target_id=row["target_id"],
        relation_type=RelationType(row["relation_type"]),
        weight=float(row.get("weight", 1.0)),
        confidence=float(row.get("confidence", 1.0)),
        created_by=row.get("created_by", "system"),
        metadata=json.loads(row.get("metadata") or "{}"),
        created_at=float(row.get("created_at", 0.0)),
    )


def _cluster_to_row(cluster: MemoryCluster) -> dict:
    return {
        "id": cluster.id,
        "collection": cluster.collection,
        "label": cluster.name,  # MemoryCluster uses 'name', not 'label'
        "cluster_type": cluster.cluster_type.value,
        "member_ids": json.dumps(cluster.node_ids or []),  # MemoryCluster uses 'node_ids', not 'member_ids'
        "summary": cluster.summary or "",
        "metadata": json.dumps(cluster.metadata or {}),
        "created_at": float(cluster.created_at),
        "updated_at": float(cluster.updated_at),
    }


def _row_to_cluster(row: dict) -> MemoryCluster:
    return MemoryCluster(
        id=row["id"],
        collection=row["collection"],
        name=row.get("label") or "",  # Database stores as 'label', but MemoryCluster field is 'name'
        cluster_type=ClusterType(row["cluster_type"]),
        node_ids=json.loads(row.get("member_ids") or "[]"),  # Database stores as 'member_ids', but MemoryCluster field is 'node_ids'
        summary=row.get("summary") or "",
        metadata=json.loads(row.get("metadata") or "{}"),
        created_at=float(row.get("created_at", 0.0)),
        updated_at=float(row.get("updated_at", 0.0)),
    )


# ---------------------------------------------------------------------------
# Backend class
# ---------------------------------------------------------------------------

class KuzuBackend(StorageBackend):
    """
    Persistent graph storage backed by KuzuDB (embedded, file-based).

    KuzuDB is a WASM-embeddable columnar graph database. It stores data in
    a local directory and requires no external services.

    Args:
        db_path: Directory where KuzuDB will store its database file (created if absent).
                 A 'kuzu.db' file will be created within this directory.
    """

    def __init__(self, db_path: str = "./stixdb_data/kuzu") -> None:
        try:
            import kuzu  # type: ignore
        except ImportError:
            raise ImportError(
                "KuzuDB is not installed. Install it with:\n"
                "  pip install kuzu\n"
                "or:\n"
                "  pip install stixdb-engine[kuzu]"
            )
        # Ensure directory exists; KuzuDB expects a file path, not a directory
        os.makedirs(db_path, exist_ok=True)
        # Construct the full file path for the database
        db_file_path = os.path.join(db_path, "kuzu.db")
        self._db = kuzu.Database(db_file_path)
        self._conn = kuzu.Connection(self._db)
        self._lock = asyncio.Lock()
        self._initialized = False
        self._upsert_count = 0
        logger.info("KuzuDB backend created", db_path=db_file_path)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _exec(self, query: str, params: Optional[dict] = None):
        """Execute a query synchronously, returning results as list[dict]."""
        if params:
            result = self._conn.execute(query, params)
        else:
            result = self._conn.execute(query)
        rows: list[dict] = []
        if result is None:
            return rows
        try:
            col_names = result.get_column_names()
            while result.has_next():
                raw = result.get_next()
                rows.append(dict(zip(col_names, raw)))
        except Exception:
            pass
        return rows

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        self._exec(_DDL_MEMORY_NODE)
        self._exec(_DDL_RELATION_EDGE)
        self._exec(_DDL_MEMORY_CLUSTER)
        self._initialized = True
        logger.info("KuzuDB schema ensured")

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def initialize(self, collection: str) -> None:
        async with self._lock:
            self._ensure_schema()
        logger.debug("KuzuDB collection ready", collection=collection)

    async def close(self) -> None:
        async with self._lock:
            try:
                self._conn.execute("CHECKPOINT")
            except Exception:
                pass
        logger.info("KuzuDB backend closed")

    async def list_collections(self) -> list[str]:
        async with self._lock:
            self._ensure_schema()
            rows = self._exec("MATCH (n:MemoryNode) RETURN DISTINCT n.collection AS c")
        return [r["c"] for r in rows]

    async def delete_collection(self, collection: str) -> bool:
        async with self._lock:
            self._ensure_schema()
            # Delete edges first (they reference nodes)
            self._exec(
                "MATCH (a:MemoryNode {collection: $c})-[r:RelationEdge]->(b:MemoryNode) DELETE r",
                {"c": collection},
            )
            self._exec(
                "MATCH (n:MemoryNode {collection: $c}) DELETE n",
                {"c": collection},
            )
            self._exec(
                "MATCH (cl:MemoryCluster {collection: $c}) DELETE cl",
                {"c": collection},
            )
        return True

    # ------------------------------------------------------------------ #
    # Nodes                                                                #
    # ------------------------------------------------------------------ #

    async def upsert_node(self, node: MemoryNode) -> None:
        row = _node_to_row(node)
        async with self._lock:
            self._ensure_schema()
            self._upsert_count += 1
            if self._upsert_count % 500 == 0:
                try:
                    self._conn.execute("CHECKPOINT")
                except Exception:
                    pass
            # Check if it already exists
            existing = self._exec(
                "MATCH (n:MemoryNode {id: $id}) RETURN n.id",
                {"id": node.id},
            )
            if existing:
                # KuzuDB requires all params in the dict to appear in the query.
                # Filter to only the keys used in the SET clause (omit created_at).
                set_params = {k: row[k] for k in (
                    "id", "content", "collection", "node_type", "tier",
                    "importance", "source", "source_agent_id", "tags",
                    "metadata", "embedding", "parent_node_ids", "pinned",
                    "updated_at", "last_accessed", "access_count",
                )}
                self._exec(
                    """
                    MATCH (n:MemoryNode {id: $id})
                    SET n.content = $content,
                        n.collection = $collection,
                        n.node_type = $node_type,
                        n.tier = $tier,
                        n.importance = $importance,
                        n.source = $source,
                        n.source_agent_id = $source_agent_id,
                        n.tags = $tags,
                        n.metadata = $metadata,
                        n.embedding = $embedding,
                        n.parent_node_ids = $parent_node_ids,
                        n.pinned = $pinned,
                        n.updated_at = $updated_at,
                        n.last_accessed = $last_accessed,
                        n.access_count = $access_count
                    """,
                    set_params,
                )
            else:
                self._exec(
                    """
                    CREATE (n:MemoryNode {
                        id: $id,
                        collection: $collection,
                        content: $content,
                        node_type: $node_type,
                        tier: $tier,
                        importance: $importance,
                        source: $source,
                        source_agent_id: $source_agent_id,
                        tags: $tags,
                        metadata: $metadata,
                        embedding: $embedding,
                        parent_node_ids: $parent_node_ids,
                        pinned: $pinned,
                        created_at: $created_at,
                        updated_at: $updated_at,
                        last_accessed: $last_accessed,
                        access_count: $access_count
                    })
                    """,
                    row,
                )

    async def get_node(self, node_id: str, collection: str) -> Optional[MemoryNode]:
        async with self._lock:
            self._ensure_schema()
            rows = self._exec(
                "MATCH (n:MemoryNode {id: $id, collection: $col}) RETURN n.*",
                {"id": node_id, "col": collection},
            )
        if not rows:
            return None
        return _row_to_node(_prefix_strip(rows[0]))

    async def delete_node(self, node_id: str, collection: str) -> bool:
        async with self._lock:
            self._ensure_schema()
            existing = self._exec(
                "MATCH (n:MemoryNode {id: $id, collection: $col}) RETURN n.id",
                {"id": node_id, "col": collection},
            )
            if not existing:
                return False
            # Remove adjacent edges (KuzuDB requires directed patterns for DELETE)
            self._exec(
                "MATCH (n:MemoryNode {id: $id})-[r:RelationEdge]->(m:MemoryNode) DELETE r",
                {"id": node_id},
            )
            self._exec(
                "MATCH (m:MemoryNode)-[r:RelationEdge]->(n:MemoryNode {id: $id}) DELETE r",
                {"id": node_id},
            )
            self._exec(
                "MATCH (n:MemoryNode {id: $id}) DELETE n",
                {"id": node_id},
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
        conditions = ["n.collection = $col"]
        params: dict = {"col": collection}
        if tier:
            conditions.append("n.tier = $tier")
            params["tier"] = tier
        if node_type:
            conditions.append("n.node_type = $node_type")
            params["node_type"] = node_type
        where = " AND ".join(conditions)
        async with self._lock:
            self._ensure_schema()
            rows = self._exec(
                f"MATCH (n:MemoryNode) WHERE {where} RETURN n.* SKIP {offset} LIMIT {limit}",
                params,
            )
        return [_row_to_node(_prefix_strip(r)) for r in rows]

    async def count_nodes(self, collection: str) -> int:
        async with self._lock:
            self._ensure_schema()
            rows = self._exec(
                "MATCH (n:MemoryNode {collection: $col}) RETURN count(n) AS cnt",
                {"col": collection},
            )
        return int(rows[0]["cnt"]) if rows else 0

    # ------------------------------------------------------------------ #
    # Edges                                                                #
    # ------------------------------------------------------------------ #

    async def upsert_edge(self, edge: RelationEdge) -> None:
        row = _edge_to_row(edge)
        async with self._lock:
            self._ensure_schema()
            # Delete existing edge with same id first (Kuzu REL tables don't support SET)
            self._exec(
                "MATCH (a:MemoryNode)-[r:RelationEdge {id: $id}]->(b:MemoryNode) DELETE r",
                {"id": edge.id},
            )
            self._exec(
                """
                MATCH (a:MemoryNode {id: $source_id}), (b:MemoryNode {id: $target_id})
                CREATE (a)-[r:RelationEdge {
                    id: $id,
                    collection: $collection,
                    relation_type: $relation_type,
                    weight: $weight,
                    confidence: $confidence,
                    created_by: $created_by,
                    metadata: $metadata,
                    created_at: $created_at
                }]->(b)
                """,
                row,
            )

    async def get_edge(self, edge_id: str, collection: str) -> Optional[RelationEdge]:
        async with self._lock:
            self._ensure_schema()
            rows = self._exec(
                """
                MATCH (a:MemoryNode)-[r:RelationEdge {id: $id, collection: $col}]->(b:MemoryNode)
                RETURN r.*, a.id AS source_id, b.id AS target_id
                """,
                {"id": edge_id, "col": collection},
            )
        if not rows:
            return None
        row = _prefix_strip(rows[0])
        row.setdefault("source_id", row.pop("a.id", ""))
        row.setdefault("target_id", row.pop("b.id", ""))
        return _row_to_edge(row)

    async def delete_edge(self, edge_id: str, collection: str) -> bool:
        async with self._lock:
            self._ensure_schema()
            existing = self._exec(
                "MATCH (a:MemoryNode)-[r:RelationEdge {id: $id, collection: $col}]->(b:MemoryNode) RETURN r.id",
                {"id": edge_id, "col": collection},
            )
            if not existing:
                return False
            self._exec(
                "MATCH (a:MemoryNode)-[r:RelationEdge {id: $id}]->(b:MemoryNode) DELETE r",
                {"id": edge_id},
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
        """BFS using Kuzu variable-length path matching."""
        if max_depth < 1:
            return []
        async with self._lock:
            self._ensure_schema()
            depth_str = f"1..{max_depth}"
            if direction == "out":
                pattern = f"(start:MemoryNode {{id: $nid}})-[r:RelationEdge*{depth_str}]->(nbr:MemoryNode)"
            elif direction == "in":
                pattern = f"(start:MemoryNode {{id: $nid}})<-[r:RelationEdge*{depth_str}]-(nbr:MemoryNode)"
            else:
                pattern = f"(start:MemoryNode {{id: $nid}})-[r:RelationEdge*{depth_str}]-(nbr:MemoryNode)"

            query = f"MATCH {pattern} WHERE nbr.collection = $col AND nbr.id <> $nid RETURN DISTINCT nbr.*"
            rows = self._exec(query, {"nid": node_id, "col": collection})
        nodes = [_row_to_node(_prefix_strip(r)) for r in rows]
        if relation_types:
            # Post-filter: Kuzu variable-length paths expose edge props differently
            # so we do a separate check for single-hop when type filtering is needed
            if max_depth == 1:
                return await self._get_neighbours_filtered(node_id, collection, direction, relation_types)
        return nodes

    async def _get_neighbours_filtered(
        self,
        node_id: str,
        collection: str,
        direction: str,
        relation_types: list[str],
    ) -> list[MemoryNode]:
        """Single-hop neighbour query with relation-type filter."""
        rt_list = ", ".join(f"'{rt}'" for rt in relation_types)
        if direction == "out":
            pattern = "(start:MemoryNode {id: $nid})-[r:RelationEdge]->(nbr:MemoryNode)"
        elif direction == "in":
            pattern = "(start:MemoryNode {id: $nid})<-[r:RelationEdge]-(nbr:MemoryNode)"
        else:
            pattern = "(start:MemoryNode {id: $nid})-[r:RelationEdge]-(nbr:MemoryNode)"

        query = (
            f"MATCH {pattern} "
            f"WHERE r.relation_type IN [{rt_list}] AND nbr.collection = $col "
            f"RETURN DISTINCT nbr.*"
        )
        rows = self._exec(query, {"nid": node_id, "col": collection})
        return [_row_to_node(_prefix_strip(r)) for r in rows]

    async def get_edges_for_node(
        self,
        node_id: str,
        collection: str,
        direction: str = "both",
    ) -> list[RelationEdge]:
        if direction == "out":
            pattern = "(n:MemoryNode {id: $nid})-[r:RelationEdge]->(m:MemoryNode)"
        elif direction == "in":
            pattern = "(n:MemoryNode {id: $nid})<-[r:RelationEdge]-(m:MemoryNode)"
        else:
            pattern = "(n:MemoryNode {id: $nid})-[r:RelationEdge]-(m:MemoryNode)"

        async with self._lock:
            self._ensure_schema()
            rows = self._exec(
                f"MATCH {pattern} WHERE r.collection = $col "
                f"RETURN r.*, n.id AS src, m.id AS tgt",
                {"nid": node_id, "col": collection},
            )
        result = []
        for row in rows:
            row = _prefix_strip(row)
            # Direction resolving: for undirected queries, src/tgt may be swapped
            if "src" in row and "tgt" in row:
                row["source_id"] = row.pop("src")
                row["target_id"] = row.pop("tgt")
            result.append(_row_to_edge(row))
        return result

    # ------------------------------------------------------------------ #
    # Clusters                                                             #
    # ------------------------------------------------------------------ #

    async def upsert_cluster(self, cluster: MemoryCluster) -> None:
        row = _cluster_to_row(cluster)
        async with self._lock:
            self._ensure_schema()
            existing = self._exec(
                "MATCH (cl:MemoryCluster {id: $id}) RETURN cl.id",
                {"id": cluster.id},
            )
            if existing:
                # KuzuDB requires all params in the dict to appear in the query.
                # Filter to only the keys used in the SET clause.
                set_params = {k: row[k] for k in ("id", "label", "cluster_type", "member_ids", "summary", "metadata", "updated_at")}
                self._exec(
                    """
                    MATCH (cl:MemoryCluster {id: $id})
                    SET cl.label = $label,
                        cl.cluster_type = $cluster_type,
                        cl.member_ids = $member_ids,
                        cl.summary = $summary,
                        cl.metadata = $metadata,
                        cl.updated_at = $updated_at
                    """,
                    set_params,
                )
            else:
                self._exec(
                    """
                    CREATE (cl:MemoryCluster {
                        id: $id,
                        collection: $collection,
                        label: $label,
                        cluster_type: $cluster_type,
                        member_ids: $member_ids,
                        summary: $summary,
                        metadata: $metadata,
                        created_at: $created_at,
                        updated_at: $updated_at
                    })
                    """,
                    row,
                )

    async def get_cluster(self, cluster_id: str, collection: str) -> Optional[MemoryCluster]:
        async with self._lock:
            self._ensure_schema()
            rows = self._exec(
                "MATCH (cl:MemoryCluster {id: $id, collection: $col}) RETURN cl.*",
                {"id": cluster_id, "col": collection},
            )
        if not rows:
            return None
        return _row_to_cluster(_prefix_strip(rows[0]))

    async def list_clusters(self, collection: str) -> list[MemoryCluster]:
        async with self._lock:
            self._ensure_schema()
            rows = self._exec(
                "MATCH (cl:MemoryCluster {collection: $col}) RETURN cl.*",
                {"col": collection},
            )
        return [_row_to_cluster(_prefix_strip(r)) for r in rows]

    async def delete_cluster(self, cluster_id: str, collection: str) -> bool:
        async with self._lock:
            self._ensure_schema()
            existing = self._exec(
                "MATCH (cl:MemoryCluster {id: $id, collection: $col}) RETURN cl.id",
                {"id": cluster_id, "col": collection},
            )
            if not existing:
                return False
            self._exec(
                "MATCH (cl:MemoryCluster {id: $id}) DELETE cl",
                {"id": cluster_id},
            )
        return True


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _prefix_strip(row: dict) -> dict:
    """
    Kuzu returns column names like 'n.id', 'n.content', etc.
    Strip the 'tablealias.' prefix so we can use them as plain keys.
    """
    out = {}
    for k, v in row.items():
        # e.g. "n.content" -> "content"
        key = k.split(".", 1)[-1] if "." in k else k
        out[key] = v
    return out

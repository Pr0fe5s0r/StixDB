"""
Collections & Memory CRUD routes.

POST   /collections/{name}/nodes             — store a memory node
GET    /collections/{name}/nodes             — list nodes
GET    /collections/{name}/nodes/{node_id}   — get single node
DELETE /collections/{name}/nodes/{node_id}   — delete node
POST   /collections/{name}/nodes/bulk        — bulk store
POST   /collections/{name}/relations         — add a relation edge
GET    /collections/{name}/stats             — graph statistics
DELETE /collections/{name}                   — delete collection data
POST   /collections/{name}/enrich            — run LLM enrichment agent
"""
from __future__ import annotations

from typing import Any, Optional, AsyncIterator
import json
import os
import tempfile

from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from stixdb.engine import StixDBEngine

router = APIRouter()


# ──────────────────────────────── Request / Response models ──────────────── #

class StoreRequest(BaseModel):
    id: Optional[str] = None
    content: str
    node_type: str = "fact"
    tier: str = "episodic"
    importance: float = 0.5
    source: Optional[str] = None
    source_agent_id: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    pinned: bool = True


class StoreResponse(BaseModel):
    node_id: str
    collection: str
    status: str = "stored"


class RelationRequest(BaseModel):
    id: Optional[str] = None
    source_node_id: str
    target_node_id: str
    relation_type: str = "relates_to"
    weight: float = 1.0
    confidence: float = 1.0
    created_by: str = "system"
    metadata: dict[str, Any] = Field(default_factory=dict)


class FolderIngestRequest(BaseModel):
    folder_path: str
    tags: list[str] = Field(default_factory=list)
    chunk_size: int = 1000
    chunk_overlap: int = 200
    parser: str = "auto"
    recursive: bool = True


# ──────────────────────────────────────── Routes ────────────────────────── #

@router.post("/{collection}/nodes", response_model=StoreResponse)
async def store_node(collection: str, body: StoreRequest, request: Request):
    """Store a new memory node in the given collection."""
    engine: StixDBEngine = request.app.state.engine
    node_id = await engine.store(
        collection=collection,
        content=body.content,
        node_type=body.node_type,
        tier=body.tier,
        importance=body.importance,
        source=body.source,
        source_agent_id=body.source_agent_id,
        tags=body.tags,
        metadata=body.metadata,
        pinned=body.pinned,
        node_id=body.id,
    )
    return StoreResponse(node_id=node_id, collection=collection)


@router.post("/{collection}/nodes/bulk")
async def bulk_store_nodes(collection: str, items: list[StoreRequest], request: Request):
    """Store multiple memory nodes in a single batched request."""
    engine: StixDBEngine = request.app.state.engine
    node_ids = await engine.bulk_store(
        collection=collection,
        items=[item.model_dump() for item in items],
    )
    return {"node_ids": node_ids, "count": len(node_ids), "collection": collection}


@router.post("/{collection}/upload")
async def upload_file(
    collection: str, 
    request: Request,
    file: UploadFile = File(...),
    tags: str = Form(""),
    chunk_size: int = Form(1000),
    chunk_overlap: int = Form(200),
    parser: str = Form("auto"),
):
    """Upload and ingest a file (TXT, PDF) directly into the collection."""
    engine: StixDBEngine = request.app.state.engine
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    
    fd, temp_path = tempfile.mkstemp(suffix=os.path.splitext(file.filename or "")[1])
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(await file.read())
            
        node_ids = await engine.ingest_file(
            collection=collection,
            filepath=temp_path,
            source_name=file.filename,
            tags=tag_list,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            parser=parser,
        )
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
    return {
        "ingested_chunks": len(node_ids), 
        "node_ids": node_ids, 
        "collection": collection, 
        "filename": file.filename,
        "parser": parser,
    }


@router.post("/{collection}/ingest/folder")
async def ingest_folder(collection: str, body: FolderIngestRequest, request: Request):
    """Ingest all supported text-like files from a server-visible folder."""
    engine: StixDBEngine = request.app.state.engine
    return await engine.ingest_folder(
        collection=collection,
        folderpath=body.folder_path,
        tags=body.tags,
        chunk_size=body.chunk_size,
        chunk_overlap=body.chunk_overlap,
        parser=body.parser,
        recursive=body.recursive,
    )


@router.get("/{collection}/nodes")
async def list_nodes(
    collection: str,
    request: Request,
    tier: Optional[str] = None,
    node_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """List memory nodes with optional filters."""
    engine: StixDBEngine = request.app.state.engine
    graph, _, _ = await engine._ensure_collection(collection)
    nodes = await graph.list_nodes(tier=tier, node_type=node_type, limit=limit, offset=offset)
    return {
        "nodes": [n.to_dict(include_embedding=False) for n in nodes],
        "count": len(nodes),
        "collection": collection,
    }


@router.get("/{collection}/nodes/{node_id}")
async def get_node(collection: str, node_id: str, request: Request):
    """Retrieve a single memory node by ID."""
    engine: StixDBEngine = request.app.state.engine
    graph, _, _ = await engine._ensure_collection(collection)
    node = await graph.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found.")
    return node.to_dict(include_embedding=False)


@router.delete("/{collection}/nodes/{node_id}")
async def delete_node(collection: str, node_id: str, request: Request):
    """Delete a memory node and all its edges."""
    engine: StixDBEngine = request.app.state.engine
    graph, _, _ = await engine._ensure_collection(collection)
    deleted = await graph.delete_node(node_id)
    return {"deleted": deleted, "node_id": node_id}


@router.post("/{collection}/relations")
async def add_relation(collection: str, body: RelationRequest, request: Request):
    """Add a typed relation edge between two nodes."""
    engine: StixDBEngine = request.app.state.engine
    edge_id = await engine.add_relation(
        collection=collection,
        source_node_id=body.source_node_id,
        target_node_id=body.target_node_id,
        relation_type=body.relation_type,
        weight=body.weight,
        confidence=body.confidence,
        created_by=body.created_by,
        metadata=body.metadata,
        edge_id=body.id,
    )
    return {"edge_id": edge_id, "collection": collection}


@router.get("/{collection}/stats")
async def get_stats(collection: str, request: Request):
    """Get high-level graph statistics for a collection."""
    engine: StixDBEngine = request.app.state.engine
    return await engine.get_graph_stats(collection)


@router.post("/{collection}/dedupe")
async def dedupe_collection(
    collection: str,
    request: Request,
    dry_run: bool = False,
):
    """
    Remove duplicate chunks from a collection.

    Runs two passes:
      1. Source-version dedup — removes older ingestions of the same file.
      2. Content-hash dedup  — removes nodes with byte-identical content.

    Set dry_run=true to preview what would be deleted without changing anything.
    """
    engine: StixDBEngine = request.app.state.engine
    return await engine.dedupe_collection(collection, dry_run=dry_run)


@router.post("/{collection}")
async def create_collection(collection: str, request: Request):
    """Create an empty collection (no-op if it already exists)."""
    engine: StixDBEngine = request.app.state.engine
    await engine._ensure_collection(collection)
    return {"collection": collection, "status": "ready"}


@router.delete("/{collection}")
async def delete_collection(collection: str, request: Request):
    """Delete all data in a collection and unload it from the engine."""
    engine: StixDBEngine = request.app.state.engine
    return await engine.delete_collection(collection)


@router.get("/{collection}/similarity-scan")
async def similarity_scan(
    collection: str,
    request: Request,
    sample: int = 120,
    top_k: int = 20,
):
    """
    Sample nodes and return pairwise cosine similarity statistics.
    Helps diagnose why consolidation is or isn't firing.
    """
    import numpy as np

    engine: StixDBEngine = request.app.state.engine
    graph, _, _ = await engine._ensure_collection(collection)
    threshold = engine.config.agent.consolidation_similarity_threshold
    synthesis_lower = engine.config.agent.synthesis_similarity_lower

    # Grab a sample of active (non-archived) nodes that have embeddings
    all_nodes = await graph.list_nodes(limit=sample * 3)
    embedded = [
        (n, np.array(n.embedding, dtype=np.float32))
        for n in all_nodes
        if n.embedding is not None
        and n.tier.value != "archived"
        and n.node_type.value != "summary"
    ][:sample]

    if len(embedded) < 2:
        return {"error": "Not enough embedded nodes to compute similarity", "count": len(embedded)}

    # Pairwise cosine similarities (upper triangle)
    similarities: list[float] = []
    top_pairs: list[dict] = []

    for i in range(len(embedded)):
        node_a, emb_a = embedded[i]
        for j in range(i + 1, len(embedded)):
            node_b, emb_b = embedded[j]
            sim = float(np.clip(np.dot(emb_a, emb_b), -1.0, 1.0))
            similarities.append(sim)
            if sim >= 0.35:  # only track potentially interesting pairs
                top_pairs.append({
                    "node_a": node_a.id[:12],
                    "node_b": node_b.id[:12],
                    "content_a": node_a.content[:80].replace("\n", " "),
                    "content_b": node_b.content[:80].replace("\n", " "),
                    "similarity": round(sim, 4),
                    "above_threshold": sim >= threshold,
                })

    top_pairs.sort(key=lambda x: x["similarity"], reverse=True)
    sims = np.array(similarities, dtype=np.float32)
    above = int(np.sum(sims >= threshold))

    return {
        "collection": collection,
        "nodes_sampled": len(embedded),
        "pairs_computed": len(similarities),
        "consolidation_threshold": threshold,
        "synthesis_lower": synthesis_lower,
        "pairs_above_threshold": above,
        "stats": {
            "min":    round(float(np.min(sims)), 4),
            "max":    round(float(np.max(sims)), 4),
            "mean":   round(float(np.mean(sims)), 4),
            "median": round(float(np.median(sims)), 4),
            "p75":    round(float(np.percentile(sims, 75)), 4),
            "p90":    round(float(np.percentile(sims, 90)), 4),
            "p95":    round(float(np.percentile(sims, 95)), 4),
            "p99":    round(float(np.percentile(sims, 99)), 4),
        },
        "top_pairs": top_pairs[:top_k],
    }


@router.get("/{collection}/graph")
async def export_graph(
    collection: str,
    request: Request,
    limit: int = 5000,
    offset: int = 0,
):
    """Export nodes and edges for a collection."""
    engine: StixDBEngine = request.app.state.engine
    graph, _, _ = await engine._ensure_collection(collection)
    nodes = await graph.list_nodes(limit=limit, offset=offset)

    edges_by_id: dict[str, dict] = {}
    for node in nodes:
        for edge in await graph.get_edges(node.id, direction="both"):
            edges_by_id[edge.id] = edge.to_dict()

    return {
        "collection": collection,
        "count": len(nodes),
        "nodes": [node.to_dict(include_embedding=False) for node in nodes],
        "edges": list(edges_by_id.values()),
    }


# ── enrich ─────────────────────────────────────────────────────────────────── #

class EnrichRequest(BaseModel):
    batch_size: int = 10
    dry_run: bool = False


@router.post("/{collection}/enrich")
async def enrich_collection(collection: str, body: EnrichRequest, request: Request):
    """
    Run the LLM enrichment agent over a collection.

    Finds cross-type node pairs with no semantic edge and asks the configured
    LLM to classify the relationship. Writes INFERRED/AMBIGUOUS edges back.

    This is Trigger 3 — on-demand. Triggers 1 (post-ingest) and 2 (background)
    fire automatically via the worker.
    """
    from stixdb.agent.enricher import Enricher, find_cross_type_pairs

    engine: StixDBEngine = request.app.state.engine
    graph, _, _ = await engine._ensure_collection(collection)

    nodes = await graph.list_nodes(limit=100_000)
    edges = await graph.list_edges()

    if body.dry_run:
        pairs = find_cross_type_pairs(nodes, nodes)
        from stixdb.agent.enricher import filter_unenriched_pairs
        unenriched = filter_unenriched_pairs(pairs, edges)
        return {
            "collection": collection,
            "dry_run": True,
            "pairs_found": len(pairs),
            "pairs_skipped": len(pairs) - len(unenriched),
            "would_enrich": len(unenriched),
        }

    enricher = Enricher(
        config=engine.config.reasoner,
        collection=collection,
        batch_size=body.batch_size,
    )

    result = await enricher.enrich_pairs(
        find_cross_type_pairs(nodes, nodes),
        edges,
    )

    # Persist the new edges
    for edge in result.edges_created:
        await graph.store_edge(edge)

    # Build a node lookup for human-readable edge details
    node_map = {n.id: n for n in nodes}
    edge_details = []
    for edge in result.edges_created:
        src = node_map.get(edge.source_id)
        tgt = node_map.get(edge.target_id)
        edge_details.append({
            "source_type": src.node_type.value if src else "?",
            "source_content": (src.content[:80] if src else edge.source_id),
            "relation": edge.relation_type.value,
            "target_type": tgt.node_type.value if tgt else "?",
            "target_content": (tgt.content[:80] if tgt else edge.target_id),
            "confidence": round(edge.confidence, 2),
            "rationale": edge.rationale or "",
        })

    return {
        "collection": collection,
        "dry_run": False,
        "edges_created": len(result.edges_created),
        "pairs_skipped": result.pairs_skipped,
        "pairs_no_relation": result.pairs_no_relation,
        "pairs_ambiguous": result.pairs_ambiguous,
        "llm_calls": result.llm_calls,
        "errors": result.errors,
        "edge_details": edge_details,
    }


@router.post("/{collection}/enrich/stream")
async def enrich_collection_stream(collection: str, body: EnrichRequest, request: Request):
    """
    SSE streaming variant of /enrich.

    Yields progress events as each batch completes so the CLI can show a live
    progress bar without waiting for the full run to finish.

    Event types:
        {"type": "start",  "total_pairs": N, "total_batches": N, "pairs_skipped": N}
        {"type": "batch",  "batch": N, "total_batches": N, "edges_this_batch": N,
                           "edges_so_far": N, "no_relation": N, "ambiguous": N}
        {"type": "done",   "edges_created": N, "pairs_skipped": N,
                           "pairs_no_relation": N, "pairs_ambiguous": N,
                           "llm_calls": N, "errors": [...], "edge_details": [...]}
    """
    from stixdb.agent.enricher import Enricher, find_cross_type_pairs, filter_unenriched_pairs

    engine: StixDBEngine = request.app.state.engine
    graph, _, _ = await engine._ensure_collection(collection)

    nodes = await graph.list_nodes(limit=100_000)
    edges = await graph.list_edges()

    if body.dry_run:
        pairs = find_cross_type_pairs(nodes, nodes)
        unenriched = filter_unenriched_pairs(pairs, edges)
        payload = json.dumps({
            "type": "done",
            "dry_run": True,
            "pairs_found": len(pairs),
            "pairs_skipped": len(pairs) - len(unenriched),
            "would_enrich": len(unenriched),
        })
        return StreamingResponse(
            iter([f"data: {payload}\n\n", "data: [DONE]\n\n"]),
            media_type="text/event-stream",
        )

    enricher = Enricher(
        config=engine.config.reasoner,
        collection=collection,
        batch_size=body.batch_size,
    )
    node_map = {n.id: n for n in nodes}

    async def event_generator() -> AsyncIterator[str]:
        async for event in enricher.enrich_pairs_stream(
            find_cross_type_pairs(nodes, nodes),
            edges,
        ):
            if event["type"] == "done":
                # Persist edges and build edge_details before sending
                created_edges = event.pop("edges_created", [])
                for edge in created_edges:
                    await graph.store_edge(edge)

                edge_details = []
                for edge in created_edges:
                    src = node_map.get(edge.source_id)
                    tgt = node_map.get(edge.target_id)
                    edge_details.append({
                        "source_type": src.node_type.value if src else "?",
                        "source_content": (src.content[:80] if src else edge.source_id),
                        "relation": edge.relation_type.value,
                        "target_type": tgt.node_type.value if tgt else "?",
                        "target_content": (tgt.content[:80] if tgt else edge.target_id),
                        "confidence": round(edge.confidence, 2),
                        "rationale": edge.rationale or "",
                    })
                event["edges_created"] = len(created_edges)
                event["edge_details"] = edge_details

            yield f"data: {json.dumps(event)}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.get("/{collection}/keywords")
async def get_collection_keywords(collection: str, request: Request):
    """
    Return keyword vocabulary for a collection.

    Lists all unique tags (sorted by frequency) and the top content terms
    derived from node text. Agents can use this to construct precise keyword
    queries against the collection without embedding API calls.
    """
    import re
    from collections import Counter

    _STOPWORDS = {
        "the", "and", "for", "are", "was", "were", "that", "this", "with",
        "from", "have", "has", "had", "but", "not", "you", "all", "can",
        "will", "its", "our", "also", "been", "they", "than", "then",
        "when", "what", "into", "more", "their", "which", "about", "would",
    }

    engine: StixDBEngine = request.app.state.engine
    graph, _, _ = await engine._ensure_collection(collection)

    nodes = await graph.list_nodes(limit=50_000, include_embedding=False)

    tag_counter: Counter = Counter()
    term_doc_freq: Counter = Counter()

    for node in nodes:
        for tag in node.tags or []:
            tag_counter[tag.lower()] += 1

        terms = {
            t for t in re.findall(r"[a-zA-Z0-9_]+", (node.content or "").lower())
            if len(t) >= 3 and t not in _STOPWORDS
        }
        for term in terms:
            term_doc_freq[term] += 1

    return {
        "collection": collection,
        "total_nodes": len(nodes),
        "tags": [
            {"tag": tag, "count": count}
            for tag, count in tag_counter.most_common(300)
        ],
        "top_terms": [term for term, _ in term_doc_freq.most_common(150)],
        "node_types": list({n.node_type.value for n in nodes}),
        "sources": list({n.source for n in nodes if n.source}),
    }

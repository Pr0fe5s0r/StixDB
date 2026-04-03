"""
Agent introspection routes.

GET  /collections/{name}/agent/status          — agent health + stats
GET  /collections/{name}/agent/working-memory  — hot nodes in working memory
POST /collections/{name}/agent/cycle           — trigger immediate agent cycle
GET  /collections/{name}/clusters              — list all memory clusters
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from stixdb.engine import StixDBEngine

router = APIRouter()


@router.get("/{collection}/agent/status")
async def agent_status(collection: str, request: Request):
    """Get the status and stats of the collection's autonomous memory agent."""
    engine: StixDBEngine = request.app.state.engine
    return await engine.get_agent_status(collection)


@router.get("/{collection}/agent/working-memory")
async def working_memory(collection: str, request: Request):
    """Return all nodes currently in the hot 'Working Memory' tier."""
    engine: StixDBEngine = request.app.state.engine
    graph, _, _ = await engine._ensure_collection(collection)
    nodes = await graph.list_nodes(tier="working", limit=500)
    return {
        "collection": collection,
        "working_memory_size": len(nodes),
        "nodes": [n.to_dict(include_embedding=False) for n in nodes],
    }


@router.post("/{collection}/agent/cycle")
async def trigger_cycle(collection: str, request: Request):
    """Manually trigger an immediate memory agent cycle."""
    engine: StixDBEngine = request.app.state.engine
    result = await engine.trigger_agent_cycle(collection)
    return {"collection": collection, "result": result}


@router.get("/{collection}/clusters")
async def list_clusters(collection: str, request: Request):
    """List all memory clusters in a collection."""
    engine: StixDBEngine = request.app.state.engine
    graph, _, _ = await engine._ensure_collection(collection)
    clusters = await graph.list_clusters()
    return {
        "collection": collection,
        "clusters": [c.to_dict() for c in clusters],
        "count": len(clusters),
    }

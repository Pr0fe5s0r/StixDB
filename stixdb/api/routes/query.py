"""
Agentic Query routes.

POST /collections/{name}/ask       — full agentic query with LLM reasoning
POST /collections/{name}/retrieve  — raw retrieval without LLM reasoning
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from typing import Optional, Any

from stixdb.engine import StixDBEngine

router = APIRouter()


class AskRequest(BaseModel):
    question: str
    top_k: int = 15
    threshold: float = 0.25
    depth: int = 2
    system_prompt: Optional[str] = None
    output_schema: Optional[dict[str, Any]] = None
    thinking_steps: int = 1    # >1 enables multi-hop reasoning loop
    hops_per_step: int = 4     # max retrieval hops per thinking step
    max_tokens: Optional[int] = None  # cap LLM response length; None = use server default


class RetrieveRequest(BaseModel):
    query: str
    top_k: int = 10
    threshold: float = 0.25
    depth: int = 1


@router.post("/{collection}/ask")
async def ask(collection: str, body: AskRequest, request: Request):
    """
    Agentic query — ask the StixDB agent a natural-language question.
    
    The agent performs semantic + graph retrieval, then uses an LLM
    to synthesise a grounded, cited answer from the memory graph.
    """
    engine: StixDBEngine = request.app.state.engine
    response = await engine.ask(
        collection=collection,
        question=body.question,
        top_k=body.top_k,
        threshold=body.threshold,
        depth=body.depth,
        system_prompt=body.system_prompt,
        output_schema=body.output_schema,
        thinking_steps=body.thinking_steps,
        hops_per_step=body.hops_per_step,
        max_tokens=body.max_tokens,
    )
    return response.to_dict()


@router.post("/{collection}/retrieve")
async def retrieve(collection: str, body: RetrieveRequest, request: Request):
    """
    Raw retrieval without LLM reasoning.
    Returns ranked memory nodes for the calling agent to process.
    """
    engine: StixDBEngine = request.app.state.engine
    nodes = await engine.retrieve(
        collection=collection,
        query=body.query,
        top_k=body.top_k,
        threshold=body.threshold,
        depth=body.depth,
    )
    return {
        "collection": collection,
        "query": body.query,
        "results": nodes,
        "count": len(nodes),
    }

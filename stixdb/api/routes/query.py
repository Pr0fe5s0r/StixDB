"""
Agentic Query routes.

POST /collections/{name}/ask       — full agentic query with LLM reasoning
POST /collections/{name}/retrieve  — raw retrieval without LLM reasoning
"""
from __future__ import annotations

import json
from time import perf_counter
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from stixdb.engine import StixDBEngine

router = APIRouter()


class AskRequest(BaseModel):
    question: str
    top_k: int = 15
    threshold: float = 0.25
    depth: int = 2
    system_prompt: Optional[str] = None
    output_schema: Optional[dict[str, Any]] = None
    max_hops: int = 8          # safety cap on agent loop iterations
    max_tokens: Optional[int] = None  # cap LLM response length; None = use server default


class RetrieveRequest(BaseModel):
    query: str
    top_k: int = 10
    threshold: float = 0.25
    depth: int = 1
    mode: str = "hybrid"


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
        max_hops=body.max_hops,
        max_tokens=body.max_tokens,
    )
    return response.to_dict()


@router.post("/{collection}/ask/stream")
async def ask_stream(collection: str, body: AskRequest, request: Request):
    """
    Streaming agentic query — same as /ask but streams as SSE.

    When thinking_steps > 1 the stream emits ``{"type": "thinking", "content": "…"}``
    events for each reasoning hop, then a final ``{"type": "answer", "content": "…"}``.
    When thinking_steps == 1 the answer tokens are streamed progressively.

    Each event is:  ``data: {"type": "thinking"|"answer"|"node_count", "content": "..."}``
    The stream ends with:  ``data: [DONE]``
    """
    engine: StixDBEngine = request.app.state.engine

    async def event_generator() -> AsyncIterator[str]:
        stream_iter = engine.stream_recursive_chat(
            collection=collection,
            question=body.question,
            max_hops=body.max_hops,
            max_tokens=body.max_tokens,
        )
        async for chunk in stream_iter:
            if chunk.get("type") == "metadata":
                continue
            yield f"data: {json.dumps(chunk)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.post("/{collection}/retrieve")
async def retrieve(collection: str, body: RetrieveRequest, request: Request):
    """
    Raw retrieval without LLM reasoning.
    Returns ranked memory nodes for the calling agent to process.
    """
    engine: StixDBEngine = request.app.state.engine
    start = perf_counter()
    nodes = await engine.retrieve(
        collection=collection,
        query=body.query,
        top_k=body.top_k,
        threshold=body.threshold,
        depth=body.depth,
        mode=body.mode,
    )
    latency_ms = (perf_counter() - start) * 1000.0
    return {
        "collection": collection,
        "query": body.query,
        "results": nodes,
        "count": len(nodes),
        "latency_ms": latency_ms,
    }

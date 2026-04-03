"""
OpenAI-compatible API routes for StixDB.
Allows StixDB to be used with standard OpenAI clients.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Optional, Any, AsyncIterator

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from stixdb.engine import StixDBEngine

router = APIRouter()


# ──────────────────────────────────────────────────────────────────────────── #
# Models                                                                       #
# ──────────────────────────────────────────────────────────────────────────── #

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: bool = False
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = None
    user: Optional[str] = None  # Used as session_id
    thinking: bool = False      # Enables Recursive Search
    verbose: bool = False       # Emit retrieval/progress updates in streamed output


# ──────────────────────────────────────────────────────────────────────────── #
# Helpers                                                                      #
# ──────────────────────────────────────────────────────────────────────────── #

def create_chat_chunk(
    content: str,
    model: str,
    *,
    chunk_id: str,
    created: int,
    finish_reason: Optional[str] = None,
    role: Optional[str] = None,
) -> str:
    """Helper to create an OpenAI-compatible SSE chunk."""
    delta: dict[str, Any] = {}
    if role:
        delta["role"] = role
    if content:
        delta["content"] = content

    data = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {json.dumps(data)}\n\n"


# ──────────────────────────────────────────────────────────────────────────── #
# Routes                                                                       #
# ──────────────────────────────────────────────────────────────────────────── #

@router.post("/chat/completions")
async def chat_completions(request: Request, body: ChatCompletionRequest):
    engine: StixDBEngine = request.app.state.engine
    
    # Map 'model' to StixDB collection
    collection = body.model
    # session_id defaults to user if provided, else a generic one
    session_id = body.user or "default_session"
    
    # Last message is the current question
    if not body.messages:
        raise HTTPException(status_code=400, detail="No messages provided")
    
    question = body.messages[-1].content

    if body.stream:
        async def stream_generator() -> AsyncIterator[str]:
            chunk_id = f"chatcmpl-{uuid.uuid4()}"
            created = int(time.time())
            emitted_progress = False

            # Match OpenAI streaming shape: first event establishes the assistant role.
            yield create_chat_chunk(
                "",
                body.model,
                chunk_id=chunk_id,
                created=created,
                role="assistant",
            )
            await asyncio.sleep(0)

            if body.verbose:
                emitted_progress = True
                yield create_chat_chunk(
                    "Searching memory graph...\n\n",
                    body.model,
                    chunk_id=chunk_id,
                    created=created,
                )
                await asyncio.sleep(0)
            
            chat_stream = (
                engine.stream_recursive_chat(
                    collection=collection,
                    question=question,
                    session_id=session_id,
                    temperature=body.temperature,
                    max_tokens=body.max_tokens,
                ) if body.thinking else engine.stream_chat(
                    collection=collection,
                    question=question,
                    session_id=session_id,
                    temperature=body.temperature,
                    max_tokens=body.max_tokens,
                )
            )

            async for chunk in chat_stream:
                chunk_type = chunk.get("type")
                if body.verbose and chunk_type == "node_count":
                    count = chunk.get("count")
                    if count is not None:
                        yield create_chat_chunk(
                            f"Retrieved {count} source excerpts. Generating answer...\n\n",
                            body.model,
                            chunk_id=chunk_id,
                            created=created,
                        )
                        await asyncio.sleep(0)
                    continue

                content = chunk.get("content", "")
                if content:
                    if body.verbose and not emitted_progress:
                        emitted_progress = True
                    yield create_chat_chunk(
                        content,
                        body.model,
                        chunk_id=chunk_id,
                        created=created,
                    )
                    await asyncio.sleep(0)
            
            yield create_chat_chunk(
                "",
                body.model,
                chunk_id=chunk_id,
                created=created,
                finish_reason="stop",
            )
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    else:
        # Blocking request
        print(f"DEBUG: Processing blocking chat completion for collection '{collection}'")
        if body.thinking:
            response = await engine.recursive_chat(
                collection=collection,
                question=question,
                session_id=session_id,
                temperature=body.temperature,
                max_tokens=body.max_tokens,
            )
        else:
            response = await engine.chat(
                collection=collection,
                question=question,
                session_id=session_id,
                temperature=body.temperature,
                max_tokens=body.max_tokens,
            )
        
        answer_text = str(response.answer)
        if not answer_text.strip() or answer_text == "{}":
             print(f"WARNING: Empty or '{{}}' answer received for question: {question}")
             answer_text = "The reasoning agent failed to produce a valid response text."

        return {
            "id": f"chatcmpl-{uuid.uuid4()}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": answer_text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }


@router.get("/models")
async def list_models(request: Request):
    engine: StixDBEngine = request.app.state.engine
    collections = await engine.list_collections_async()
    
    return {
        "object": "list",
        "data": [
            {
                "id": col,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "stix",
            }
            for col in collections
        ],
    }


@router.post("/embeddings")
async def create_embeddings(request: Request, body: dict):
    engine: StixDBEngine = request.app.state.engine
    input_text = body.get("input")
    
    if not input_text:
        raise HTTPException(status_code=400, detail="No input provided")
        
    if isinstance(input_text, str):
        texts = [input_text]
    else:
        texts = input_text
        
    embeddings = []
    for text in texts:
        vector = await engine._embedding_client.embed_query(text)
        embeddings.append(vector)
        
    return {
        "object": "list",
        "data": [
            {
                "object": "embedding",
                "index": i,
                "embedding": emb,
            }
            for i, emb in enumerate(embeddings)
        ],
        "model": body.get("model", "stix-embedding"),
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }

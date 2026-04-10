"""
StixDB FastAPI REST Server.

Exposes the full StixDBEngine over HTTP.
Run with:
    uvicorn stixdb.api.server:app --host 0.0.0.0 --port 8080 --reload
    
Or via CLI:
    stixdb serve
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from stixdb.engine import StixDBEngine
from stixdb.config import StixDBConfig
from stixdb.api.routes import collections, query, agent, openai, search


# ──────────────────────────────────────────────────────────────────────────── #
# App state                                                                    #
# ──────────────────────────────────────────────────────────────────────────── #

engine: StixDBEngine = None  # type: ignore


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage engine lifecycle with the FastAPI lifespan protocol.

    Config resolution order:
      1. STIXDB_PROJECT_DIR/.stixdb/config.json   (STIXDB_PROJECT_DIR = home dir, set by `stixdb serve/daemon`)
      2. .stixdb/config.json in cwd
      3. Environment variables / defaults
    """
    global engine
    import logging
    config = StixDBConfig.load()   # smart loader: file → env → defaults
    engine = StixDBEngine(config=config)
    try:
        await engine.start()
    except RuntimeError as exc:
        msg = str(exc)
        if "not enough space" in msg or "Error 112" in msg or "No space left" in msg:
            logging.critical(
                "StixDB startup failed — DISK FULL.\n"
                f"  Storage path: {config.storage.data_dir}\n"
                "  Free up disk space or change 'storage.path' in ~/.stixdb/config.json.\n"
                "  To reclaim space: start the server once disk is freed, then run\n"
                "    stixdb compact\n"
                "  to rebuild the KuzuDB file at its minimum size."
            )
        else:
            logging.critical("StixDB engine failed to start: %s", exc)
        raise
    except Exception as exc:
        logging.critical("StixDB engine failed to start: %s", exc)
        raise
    app.state.engine = engine
    yield
    await engine.stop()


# ──────────────────────────────────────────────────────────────────────────── #
# App factory                                                                  #
# ──────────────────────────────────────────────────────────────────────────── #

app = FastAPI(
    title="StixDB — Agentic Context DB",
    description=(
        "StixDB is a Reasoning Agentic Context Database. "
        "An autonomous AI agent lives inside each collection, "
        "managing a self-organising graph memory layer for other agents."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    # Allow docs, openapi, and root/health to be public
    if request.url.path in ["/docs", "/openapi.json", "/health", "/"]:
        return await call_next(request)
        
    engine_state = getattr(request.app.state, "engine", None)
    if engine_state and engine_state.config.api.api_key:
        api_key = request.headers.get("X-API-Key") or request.headers.get("Authorization")
        expected = engine_state.config.api.api_key
        
        # Check standard Authorization Bearer or custom X-API-Key headers
        if not api_key or (api_key != expected and api_key != f"Bearer {expected}"):
            return JSONResponse(status_code=403, content={"error": "Invalid or missing API key"})
            
    return await call_next(request)


# ──────────────────────────────────────────────────────────────────────────── #
# Global exception handler                                                     #
# ──────────────────────────────────────────────────────────────────────────── #

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": str(exc), "type": type(exc).__name__},
    )


# ──────────────────────────────────────────────────────────────────────────── #
# Routes                                                                        #
# ──────────────────────────────────────────────────────────────────────────── #

app.include_router(collections.router, prefix="/collections", tags=["Memory"])
app.include_router(query.router, prefix="/collections", tags=["Query"])
app.include_router(agent.router, prefix="/collections", tags=["Agent"])
app.include_router(search.router, tags=["Search"])
app.include_router(openai.router, prefix="/v1", tags=["OpenAI"])


@app.get("/", tags=["Health"])
async def root():
    return {
        "service": "StixDB Agentic Context DB",
        "version": "0.1.0",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
async def health(request: Request):
    eng: StixDBEngine = request.app.state.engine
    return {
        "status": "ok",
        "collections": await eng.list_collections_async(),
    }


@app.post("/storage/compact", tags=["Storage"])
async def compact_storage(request: Request):
    """
    Reclaim wasted disk space by rebuilding the KuzuDB file.

    KuzuDB pre-allocates buffer-pool-sized pages (~80% of system RAM by default),
    causing the file to balloon to gigabytes even for small datasets.
    This endpoint exports all data, deletes the old file, recreates it with a
    controlled 256 MB buffer pool, and reimports everything.
    """
    eng: StixDBEngine = request.app.state.engine
    return await eng.compact_storage()


@app.get("/traces", tags=["Observability"])
async def get_traces(
    request: Request,
    collection: str | None = None,
    event_type: str | None = None,
    limit: int = 50,
):
    """Retrieve agent thinking traces."""
    eng: StixDBEngine = request.app.state.engine
    return {"traces": eng.get_traces(collection=collection, event_type=event_type, limit=limit)}

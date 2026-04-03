# System Architecture

## Top-Level Shape

The central object in StixDB is `StixDBEngine`.

It coordinates:

- storage
- vector search
- embeddings
- session history
- collection-specific memory agents
- collection-specific context brokers

## Main Components

### StixDBEngine

File:
- `stix/engine.py`

Responsibilities:

- lifecycle management
- collection initialization
- store and ingest operations
- question answering
- chat and streaming chat
- recursive multi-hop chat
- maintenance workflows

This is the main orchestration layer and the object that the HTTP server uses.

### MemoryGraph

File:
- `stix/graph/memory_graph.py`

Responsibilities:

- node CRUD
- edge CRUD
- cluster CRUD
- vector-backed semantic search
- graph expansion
- node hydration from storage

`MemoryGraph` is the unified memory access layer. It sits between the higher-level engine/broker logic and the lower-level storage/vector components.

### StorageBackend

Files:

- `stix/storage/base.py`
- `stix/storage/networkx_backend.py`
- `stix/storage/kuzu_backend.py`
- `stix/storage/neo4j_backend.py`

Responsibilities:

- persistence of nodes and edges
- graph traversal
- collection management

Supported modes:

- in-memory NetworkX (ephemeral, dev/testing)
- persistent KuzuDB (local development, no Docker)
- Neo4j (production, Docker)

### VectorStore

File:
- `stix/storage/vector_store.py`

Responsibilities:

- embedding storage
- vector similarity search

Supported backends:

- in-memory NumPy search
- Chroma
- Qdrant

### EmbeddingClient

File:
- `stix/storage/embeddings.py`

Responsibilities:

- generating embeddings for stored content and user queries

Supported providers:

- sentence-transformers
- OpenAI-style embedding APIs
- Ollama
- custom OpenAI-compatible embedding providers

### ContextBroker

File:
- `stix/context/broker.py`

Responsibilities:

- query retrieval pipeline
- reranking
- memory access recording
- reasoner invocation
- reflective caching

The broker is the main query-routing layer for a collection.

### Reasoner

File:
- `stix/agent/reasoner.py`

Responsibilities:

- build prompts from retrieved context
- call the configured LLM provider
- parse structured responses
- stream raw answer deltas

Supported providers:

- OpenAI
- Anthropic
- Ollama
- custom OpenAI-compatible providers
- heuristic fallback when no LLM is configured

### MemoryAgent

Files:

- `stix/agent/memory_agent.py`
- `stix/agent/worker.py`
- `stix/agent/consolidator.py`
- `stix/agent/maintenance.py`
- `stix/agent/planner.py`

Responsibilities:

- observe memory access
- classify hot vs cold memory
- trigger maintenance work
- consolidate or summarize memory over time

This is what makes StixDB "agentic" rather than just a passive retrieval layer.

### SessionManager

File:
- `stix/agent/sessions.py`

Responsibilities:

- maintain multi-turn session history
- support stateful chat workflows

## Collection Model

StixDB is organized around collections.

Each collection has its own:

- graph
- broker
- memory agent

This provides logical isolation between different memory spaces such as:

- one app
- one tenant
- one assistant
- one project

## Request Flows

### 1. Store memory

Flow:

1. API receives a store request
2. `StixDBEngine.store()` is called
3. node embedding is created
4. node is persisted in graph storage
5. embedding is persisted in vector storage
6. tracer/agent access infrastructure is updated

### 2. Retrieval-only query

Flow:

1. caller hits `/collections/{collection}/retrieve` or `/search`
2. query embedding is created
3. vector search returns seed hits
4. graph neighbors are expanded
5. results are reranked and filtered
6. structured search results are returned

### 3. Answer generation

Flow:

1. retrieval pipeline prepares context
2. top context nodes are passed to the reasoner
3. reasoner builds prompt and calls the model
4. reasoner parses or streams model output
5. response is returned with answer, reasoning, sources, and confidence

### 4. Streaming answer generation

Flow:

1. `/v1/chat/completions` starts an SSE stream
2. retrieval runs inside the engine path
3. reasoner requests streamed output from the model
4. raw answer deltas are forwarded immediately
5. final metadata/fallback handling occurs after stream completion

### 5. Recursive thinking mode

Flow:

1. run retrieval for the current query
2. reason over accumulated nodes
3. decide if the answer is complete
4. if incomplete, generate the next query
5. repeat until complete or max hops reached

## Compatibility Layer

The HTTP server exposes multiple styles of API on top of the same engine:

- native CRUD/query routes
- OpenAI-compatible routes
- search-centric routes

This is important because it lets StixDB act as either:

- a backend memory service
- or a drop-in chat endpoint for OpenAI-style clients

## Observability

StixDB includes observability hooks for:

- query traces
- reasoning traces
- maintenance events
- metrics

This helps debug both latency and memory quality over time.

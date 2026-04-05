# StixDB Project Guide

## Purpose

StixDB is a Python-based agentic memory system that combines:

- a graph-backed memory model
- semantic retrieval and vector search
- an autonomous maintenance agent per collection
- grounded question answering over stored memory
- an HTTP API, OpenAI-compatible API surface, and Python SDK

In practical terms, StixDB lets applications store facts, events, entities, documents, and derived summaries in a memory graph, then query that graph through retrieval-first reasoning rather than plain keyword lookup.

This guide is intended to be the primary open-source onboarding document for:

- developers evaluating the project
- contributors reading the codebase for the first time
- application teams integrating StixDB into their own agents or products

## What Problem StixDB Solves

Most application databases store data passively. Retrieval quality, memory consolidation, context ranking, and answer synthesis are pushed outward into another application layer.

StixDB moves part of that responsibility inward. Each collection has an internal memory agent that continuously maintains the memory graph by:

- tracking which nodes are active or cold
- consolidating semantically similar memories
- creating summaries when auto-summarization is enabled
- pruning low-value memories over time
- preserving source lineage for grounded answers

The result is a database-like system optimized for agent memory and context retrieval rather than only row storage.

## Core Concepts

### Collection

A collection is the main isolation boundary in StixDB.

Each collection has its own:

- `MemoryGraph`
- `MemoryAgent`
- `ContextBroker`
- retrieval state and maintenance loop

Examples:

- one collection per end user
- one collection per workspace or project
- one collection per autonomous agent

### Memory Node

Memories are stored as graph nodes with content and metadata.

Important fields include:

- `content`
- `node_type`
- `tier`
- `importance`
- `source`
- `tags`
- `metadata`
- `pinned`

Common node types:

- `fact`
- `entity`
- `event`
- `concept`
- `procedure`
- `summary`

### Memory Tier

The tier models how StixDB treats a memory over time.

- `working`: hot memories that are frequently accessed
- `episodic`: recent and contextual memories
- `semantic`: generalized knowledge
- `procedural`: process or skill-oriented knowledge
- `archived`: cold memories that may be pruned or deprioritized

### Relation Edge

Nodes can be connected with typed edges to express relationships between memories. This allows retrieval to expand from initial semantic matches into related context.

### Lineage

Lineage is a first-class concept during ingestion and summarization.

StixDB preserves provenance by storing source metadata such as:

- PDF page references
- text chunk offsets
- backup references
- parent support nodes for summaries

When `STIXDB_AGENT_LINEAGE_SAFE_MODE=true`, support nodes used for summaries are protected from destructive cleanup.

## High-Level Architecture

StixDB is organized around a small number of core runtime components:

- `StixDBEngine`: top-level async API and orchestration layer
- `MemoryGraph`: node, edge, clustering, and retrieval operations
- `MemoryAgent`: autonomous maintenance loop for each collection
- `ContextBroker`: retrieval plus reasoning pipeline
- `Reasoner`: LLM-backed or heuristic answer generation
- storage backends: graph persistence and vector index implementations
- FastAPI server: HTTP entry point for apps and external agents

Typical flow for a grounded question:

1. A client sends a question to the engine or API.
2. StixDB retrieves candidate nodes using semantic search.
3. StixDB expands into related graph context.
4. The broker assembles relevant nodes.
5. The reasoner synthesizes an answer from retrieved evidence.
6. The response includes answer text, confidence, reasoning trace, and sources.

Typical flow for background maintenance:

1. A collection agent wakes on its configured interval.
2. It evaluates access patterns, decay, and similarity.
3. It promotes, demotes, merges, summarizes, or prunes memories.
4. It updates graph state and emits traces and metrics.

## Repository Map

The repository is intentionally split by responsibility.

### Core package

`stix/`

Primary application package containing:

- engine lifecycle and public API
- configuration
- graph models and graph logic
- autonomous agent logic
- retrieval and reasoning
- ingestion
- storage backends
- API server and routes
- tracing and observability

### SDK

`sdk/`

Separate Python package for consumers who want a lightweight HTTP client rather than importing the engine directly.

### Examples

`examples/`

Runnable examples grouped by use case:

- `core/`
- `agents/`
- `ai_generated/openai/`
- `search/`

### Documentation

`doc/`

Project documentation, including architecture and performance notes.

### Tests

`tests/`

Pytest suite covering graph behavior, agent behavior, lineage, search API, OpenAI compatibility, and SDK usage.

### Supporting assets

- `scripts/`: development helpers and tooling
- `demos/`: experiments and standalone demo work
- `my_test_app/`: local integration playground

## Runtime Surfaces

StixDB exposes three main ways to use the system.

### 1. Python engine API

Use this when your application runs in the same Python process and you want the most direct control.

Primary entry point:

- `stixdb.engine.StixDBEngine`

Key methods include:

- `start()`
- `stop()`
- `store()`
- `bulk_store()`
- `ingest_file()`
- `ingest_folder()`
- `ask()`
- `retrieve()`
- `chat()`
- `stream_chat()`
- `recursive_chat()`
- `stream_recursive_chat()`
- `trigger_agent_cycle()`
- `get_agent_status()`
- `get_graph_stats()`

### 2. REST API

Use this when StixDB is running as a standalone service.

Main route groups:

- `/health`
- `/traces`
- `/collections/{collection}/nodes`
- `/collections/{collection}/nodes/bulk`
- `/collections/{collection}/upload`
- `/collections/{collection}/ingest/folder`
- `/collections/{collection}/relations`
- `/collections/{collection}/stats`
- `/collections/{collection}/graph`
- `/collections/{collection}/ask`
- `/collections/{collection}/retrieve`
- `/search`

Interactive docs are available at `/docs` when the server is running.

### 3. OpenAI-compatible API

StixDB also exposes `/v1` routes for applications that already speak OpenAI-style chat semantics.

This is useful for:

- chat completion compatibility
- streaming answer deltas
- integrating StixDB with existing OpenAI client code

This surface is especially useful when you want StixDB-backed retrieval with a familiar client interface.

## Storage Model

StixDB separates graph storage from vector retrieval storage.

### Graph backends

- `memory`: in-process NetworkX, no persistence — development & ephemeral testing
- `kuzu`: KuzuDB embedded graph, persistent on disk — **recommended for local development** (no Docker)
- `neo4j`: Neo4j graph database, scalable persistence — production via Docker

### Vector backends

- `memory`: numpy-based in-memory search — ephemeral, fast for small datasets
- `chroma`: medium-scale vector persistence — embedded locally or via Docker
- `qdrant`: high-performance vector database — requires Docker for production

**Data persistence across all tiers:**

| Mode | Graph | Vectors | Metadata | Files |
|------|-------|---------|----------|-------|
| `memory` | RAM | RAM | RAM | Not stored |
| `kuzu` (local dev) | Disk (KuzuDB) | Disk (SQLite via Chroma) | Disk | Uploaded dir |
| `neo4j` (Docker) | Docker volume | Docker volume | Docker volume | MinIO |

With `memory` mode, all state is lost on restart. With `kuzu` and `neo4j`, data persists across restarts.

## LLM and Embedding Providers

Reasoning and embedding are configurable independently.

### Reasoning providers

- `openai`
- `anthropic`
- `ollama`
- `custom`
- `none`

`none` is especially valuable for:

- tests
- local development
- deterministic behavior during debugging

### Embedding providers

- `sentence_transformers`
- `openai`
- `ollama`
- `custom`

## Ingestion Model

StixDB supports both direct text storage and document ingestion.

Current ingestion workflows include:

- storing freeform memory content with metadata
- ingesting single files
- ingesting entire folders
- uploading documents through the API

The ingestion pipeline:

1. reads the file
2. extracts segments
3. chunks content into manageable memory units
4. records provenance metadata
5. stores each chunk as a memory node
6. creates embeddings and indexes the chunks

Supported workflows are designed around text-like files and PDFs. The code also includes parser handling for `auto`, `legacy`, and optional `docling`-based extraction.

## Autonomous Agent Behavior

One of the defining features of StixDB is that each collection has a background memory agent.

Its responsibilities include:

- access tracking
- memory decay
- hot or cold memory management
- consolidation of similar nodes
- optional summary generation
- maintenance planning

Important tuning knobs from `AgentConfig`:

- `cycle_interval_seconds`
- `consolidation_similarity_threshold`
- `decay_half_life_hours`
- `prune_importance_threshold`
- `working_memory_max_nodes`
- `max_consolidation_batch`
- `enable_auto_summarize`
- `lineage_safe_mode`

For open-source readers, this is the part of the project that makes StixDB more than a retrieval wrapper. The database is designed to self-maintain its memory graph over time.

## Retrieval and Reasoning

StixDB has two distinct retrieval modes.

### Retrieve

`retrieve()` and `POST /collections/{collection}/retrieve` return ranked nodes without answer synthesis.

Use this when:

- your application wants raw evidence
- you already have your own reasoning layer
- you need explicit control over answer generation

### Ask

`ask()` and `POST /collections/{collection}/ask` perform retrieval and then synthesize a grounded answer.

Use this when:

- you want a direct answer
- you want cited or source-aware reasoning
- you want StixDB to act as the memory reasoning layer for your application

### Search API

`POST /search` is designed more like a product search surface than a chat endpoint.

It supports:

- single-query search
- multi-query search
- cross-collection search
- filtering by source, tag, node type, and tier
- optional heatmap signals
- ranking by relevance, heat, or hybrid scoring

This makes StixDB usable both as:

- a reasoning system
- a search product backend

## Configuration

The primary configuration entry point is `StixDBConfig`, which groups:

- `AgentConfig`
- `ReasonerConfig`
- `StorageConfig`
- `EmbeddingConfig`
- `ApiServerConfig`
- `BackupConfig`

Configuration can be supplied:

- directly in Python
- through environment variables
- through `.env` files loaded at startup

Important environment variables include:

- `STIXDB_LLM_PROVIDER`
- `STIXDB_LLM_MODEL`
- `STIXDB_LLM_TEMPERATURE`
- `STIXDB_STORAGE_MODE`
- `STIXDB_DATA_DIR`
- `STIXDB_VECTOR_BACKEND`
- `STIXDB_EMBEDDING_PROVIDER`
- `STIXDB_EMBEDDING_MODEL`
- `STIXDB_API_PORT`
- `STIXDB_API_KEY`
- `STIXDB_ENABLE_TRACES`
- `STIXDB_ENABLE_METRICS`
- `STIXDB_METRICS_PORT`
- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `OLLAMA_BASE_URL`

There is also optional backup support for ingestion-time file retention through MinIO-compatible object storage.

## Local Development Setup

### Requirements

- Python 3.10 or newer
- pip
- optional provider credentials depending on your chosen LLM or embedding backend

### Install the project

```bash
pip install -e .
```

For development tools:

```bash
pip install -e .[dev]
```

For optional backends, install the relevant extras as needed, for example:

```bash
pip install -e .[neo4j,qdrant,local,docling]
```

### Start the API server

```bash
stixdb serve --port 4020
```

Then open:

- `http://localhost:4020/health`
- `http://localhost:4020/docs`

### Run example scripts

Examples that match the current repository layout include:

```bash
python examples/core/basic_usage.py
python examples/agents/multi_agent_demo.py
python examples/search/01_search_api.py
python examples/ai_generated/openai/03_streaming_chat.py
```

### Run tests

```bash
pytest tests/ -v
```

## Deployment & Local Setup

### Three deployment tiers

**Tier 1: Learning / Testing (MEMORY mode)**
```bash
pip install stixdb-engine
python my_script.py
```
Data persists only while the process runs. Perfect for tutorials and experiments.

**Tier 2: Local Development (KUZU mode)** — ✅ **RECOMMENDED**
```bash
pip install "stixdb-engine[local-dev]"   # adds KuzuDB and sentence-transformers
```
All data persists to `./stixdb_data/kuzu/` on disk. Restart the process anytime, data is still there.
No Docker required. Full agent cycles, Search API, and Sonar API available.

**Tier 3: Production (NEO4J + Docker)**
```bash
docker compose up -d
```
Scalable, multi-agent, with audit trails and backups. See the main README for details.

### Docker Compose stack (Tier 3)

The `docker-compose.yml` provisions four services:

| Service | Role | Ports | Data |
|---------|------|-------|------|
| `stixdb-engine` | REST API + agent | `4020` | ChromaDB (embedded) |
| `neo4j` | Graph storage | `7474`, `7687` | Neo4j volumes |
| `postgres` | SQL metadata | `5432` | PostgreSQL volumes |
| `minio` | File backup | `9000`, `9001` | MinIO volumes |

### When to use each tier

| Use Case | Tier | Command |
|----------|------|---------|
| Learning StixDB | MEMORY | `pip install stixdb-engine` |
| Building locally | KUZU | `pip install stixdb-engine[local-dev]` |
| Production / scaling | NEO4J | `docker compose up -d` |
| Team collaboration | NEO4J | `docker compose up -d` |
| Multi-agent system | NEO4J | `docker compose up -d` |

### Docker setup (quick start)

```bash
# Copy env and set API keys
cp .env.example .env
# Edit .env: set OPENAI_API_KEY or ANTHROPIC_API_KEY

# Start the full stack
docker compose up -d

# Verify
curl http://localhost:4020/health
```

### Data flow per tier

**Tier 1 (MEMORY)**
```
store() → NetworkX graph (RAM) + NumPy vectors (RAM)
```

**Tier 2 (KUZU)**
```
store() → KuzuDB graph (disk) + ChromaDB vectors (disk)
         → ./stixdb_data/kuzu/
```

**Tier 3 (NEO4J + Docker)**
```
store() → Neo4j graph (Docker volume)
       → ChromaDB vectors (Docker volume)
       → PostgreSQL metadata (Docker volume)
       → MinIO files (Docker volume) [if backup enabled]
```

### Shutdown and reset

```bash
# Tier 2 (KUZU)
rm -rf ./stixdb_data           # deletes all local data

# Tier 3 (Docker)
docker compose down            # stop containers, preserve volumes
docker compose down -v         # stop + delete all volumes (full reset)
```

## SDK Overview

The SDK in `sdk/` is a separate consumer-facing package.

Use it when you want:

- a simple synchronous client
- an async client
- memory CRUD helpers
- file upload and folder ingestion helpers
- search and query wrappers around the HTTP API

Import path:

```python
from stixdb_sdk import StixDBClient, AsyncStixDBClient
```

The SDK is intentionally separate from the engine package so application teams can use a stable HTTP client without importing internal runtime code.

## Observability

StixDB has built-in observability features for agentic systems.

Current surfaces include:

- `/health` for service health
- `/traces` for agent and reasoning traces
- Prometheus metrics when enabled
- internal structured logging through `structlog`

For open-source users, this is especially important because debugging retrieval and autonomous maintenance behavior is harder than debugging a standard CRUD service.

## Testing Strategy

The test suite suggests the project currently focuses on:

- graph correctness
- agent behavior
- lineage behavior
- search API behavior
- OpenAI-compatible API behavior
- SDK behavior

This is a healthy shape for an open-source system because it tests both:

- internal runtime behavior
- public integration surfaces

## Suggested Contributor Workflow

For a new contributor, the most effective reading order is:

1. Read this guide.
2. Read `README.md` for the project pitch and quick start.
3. Read `doc/architecture/11-system-architecture.md`.
4. Read `stix/engine.py` to understand the top-level runtime flow.
5. Read the API routes under `stix/api/routes/`.
6. Read tests that match the surface you want to change.

When contributing code:

1. choose the public surface you are affecting
2. trace it into the engine and graph layers
3. update or add tests near the changed behavior
4. update docs for any public-facing contract changes

## Open-Source Strengths

From a maintainer and contributor perspective, the project already has several strong open-source qualities:

- clear domain focus
- meaningful architecture separation
- multiple usage surfaces
- automated tests around public APIs
- examples for key workflows
- deployable container configuration

## Areas To Keep Improving

As the project matures, the highest-value documentation and maintenance improvements are likely:

- keeping the README fully aligned with the actual repo layout and commands
- documenting supported file types and parser behavior in one place
- documenting response schemas for key endpoints more formally
- adding architecture diagrams for ingestion, retrieval, and maintenance loops
- publishing a contributor guide and issue templates
- publishing a roadmap and versioning policy

## Recommended Docs Set For Open Source

For a polished open-source launch, the minimum recommended top-level documentation set is:

- `README.md`: project pitch, quick start, and feature overview
- `doc/architecture/00-project-guide.md`: this contributor and evaluator guide
- `doc/architecture/11-system-architecture.md`: deeper technical architecture
- `CONTRIBUTING.md`: contributor workflow, coding standards, and PR expectations
- `LICENSE`: already present in package metadata and should also exist as a root file if not already added separately
- `SECURITY.md`: reporting process for vulnerabilities
- `CHANGELOG.md`: release history and upgrade notes

## Summary

StixDB is best understood as an agentic memory platform rather than only a vector database or only a chat wrapper.

Its distinguishing idea is that memory inside the system is actively maintained by per-collection agents, while retrieval, reasoning, search, ingestion, and provenance are exposed through developer-friendly APIs.

That combination gives the project a strong open-source story:

- interesting technical differentiation
- practical developer integration surfaces
- room for both research-oriented and production-oriented contributions

# Repo Organization

## Top-Level Layout

### `stix/`

The main application package.

This is where the engine, API, graph, storage, and agent logic live.

### `tests/`

Automated tests for:

- graph behavior
- agent behavior
- search API
- OpenAI-compatible API
- SDK behavior

### `sdk/`

Python SDK for the StixDB HTTP API.

This is useful for app developers who want a small wrapper instead of calling REST manually.

Suggested structure:

- `sdk/src/stixdb_sdk/`
  installable SDK package

- `sdk/examples/`
  runnable SDK usage examples

- `sdk/README.md`
  SDK-specific quickstart

### `examples/`

Usage examples organized by category.

Suggested structure:

- `examples/core/`
- `examples/agents/`
- `examples/ai_generated/`
- `examples/search/`

### `doc/`

Documentation for architecture and the recent performance/streaming changes.

Suggested structure:

- `doc/architecture/`
- `doc/performance/`

### `scripts/`

Operational helper scripts that are useful during development but are not part of the package itself.

Suggested structure:

- `scripts/benchmarks/`
- `scripts/debug/`
- `scripts/manual/`

### `demos/`

Standalone demos and sandboxes that are useful for experimentation but should not crowd the project root.

## `stix/` Package Breakdown

### `stix/api/`

HTTP server and route definitions.

Important files:

- `server.py`
  FastAPI app setup, middleware, engine lifecycle, route registration

- `routes/collections.py`
  memory CRUD, upload/ingest, stats, graph export

- `routes/query.py`
  ask and retrieve endpoints

- `routes/agent.py`
  agent status, working memory, clusters, trigger cycle

- `routes/search.py`
  product-style search API

- `routes/openai.py`
  OpenAI-compatible API surface

### `stix/agent/`

Autonomous memory management and reasoning support.

Important files:

- `reasoner.py`
  LLM prompt building, reasoning, streaming, parsing

- `memory_agent.py`
  high-level memory agent behavior

- `worker.py`
  async background cycle execution

- `planner.py`
  access scoring and prioritization

- `consolidator.py`
  memory merge/prune logic

- `maintenance.py`
  maintenance orchestration

- `sessions.py`
  chat/session history tracking

### `stix/context/`

Query orchestration and final response assembly.

Important files:

- `broker.py`
  retrieval + reasoning pipeline

- `response.py`
  response model returned to callers

### `stix/graph/`

Graph-domain models and graph-facing operations.

Important files:

- `memory_graph.py`
  central graph access API

- `node.py`
  memory node model

- `edge.py`
  relation edge model

- `cluster.py`
  cluster model

### `stix/storage/`

Persistence, embeddings, and vector search.

Important files:

- `base.py`
  storage backend interface

- `networkx_backend.py`
  in-memory graph backend (ephemeral, dev/testing)

- `kuzu_backend.py`
  persistent KuzuDB backend (local development, no Docker)

- `neo4j_backend.py`
  Neo4j graph backend (production, Docker)

- `vector_store.py`
  vector search backend abstraction

- `embeddings.py`
  embedding provider abstraction

### `stix/observability/`

Tracing and metrics support.

### `stix/config.py`

Global configuration models for:

- storage
- embeddings
- reasoner
- agent
- API server

This file is the central definition of runtime knobs.

### `stix/cli.py`

CLI entrypoint for running the app.

## Design Philosophy in the Repo

The codebase is organized by responsibility rather than by framework layer alone.

Examples:

- graph operations are not mixed into HTTP routes
- retrieval orchestration is not mixed into raw storage backends
- model-calling code is isolated in the reasoner

That separation makes it easier to:

- swap storage backends
- swap vector backends
- support different LLM providers
- expose multiple APIs on top of one engine

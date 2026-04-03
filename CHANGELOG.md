# Changelog

All notable changes to StixDB are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
StixDB uses [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Planned
- Pinecone vector backend
- Multi-hop graph reasoning traces UI
- Collection-level RBAC
- Webhook callbacks on agent cycle events

---

## [0.1.0] — 2025-01-01

### Added
- **StixDBEngine** — top-level async engine managing multiple isolated collections
- **MemoryGraph** — unified graph + vector store interface (NetworkX / KuzuDB / Neo4j)
- **MemoryAgent** — per-collection autonomous background agent
  - `AccessPlanner` — hybrid LRU+LFU heat scoring for node tier promotion
  - `Consolidator` — cosine-similarity merging (threshold 0.88) + exponential decay pruning
  - `MemoryAgentWorker` — decoupled `perceive → plan → act` async loop (30s default)
- **ContextBroker** — 7-phase retrieval: embed → vector search → graph BFS → re-rank → truncate → LLM reason → record
- **Reasoner** — LLM synthesis over graph context (OpenAI / Anthropic / Ollama / Custom / None)
- **REST API** (FastAPI)
  - Collection CRUD, bulk ingest, file upload
  - `POST /collections/{id}/ask` — agentic Q&A
  - `POST /search` — multi-query, cross-collection, filterable search
  - `GET /collections/{id}/agent/status` — agent introspection
  - `GET /traces` — execution trace log
  - OpenAI-compatible `/v1/chat/completions`, `/v1/models`, `/v1/embeddings`
- **Python SDK** (`stixdb-sdk`) — sync + async HTTP client
- **Storage backends**: NetworkX (ephemeral), KuzuDB (local persistent, no Docker), Neo4j (Docker, production)
- **Vector backends**: NumPy (in-process), ChromaDB, Qdrant
- **Embedding providers**: sentence-transformers, OpenAI, Ollama, custom OpenAI-compatible
- **Memory tiers**: `working`, `episodic`, `semantic`, `procedural`, `archived`
- **Node types**: `fact`, `entity`, `event`, `concept`, `procedure`, `summary`, `question`
- **Lineage safety mode** — source nodes pinned across consolidation cycles
- **Document ingestion** — PDF (page-level provenance), plain text (character offset chunking)
- **Observability** — structlog, Prometheus metrics, distributed trace log
- **Docker Compose** stack — StixDB + Neo4j + ChromaDB + PostgreSQL
- **CLI** — `stixdb serve`, `stixdb demo`, `stixdb multi-demo`
- Full test suite — agent, graph, lineage, search API, OpenAI compatibility, SDK

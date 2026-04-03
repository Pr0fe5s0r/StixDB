# StixDB — Comprehensive Guide

> "An autonomous AI agent lives inside your database."

StixDB is a **Reasoning Agentic Context Database**. It isn't just a place to store vectors or graph nodes — it's a self-maintaining memory system designed to act as the cognitive heart of your autonomous agents.

This guide provides an end-to-end technical breakdown of the system, from the top-level API down to the autonomous maintenance cycles.

---

## 1. System Architecture

StixDB follows a hierarchical design where the `StixDBEngine` orchestrates multiple `Collections`. Each collection is a fully-isolated memory instance.

### Core Runtime Components

| Component | Responsibility |
|-----------|----------------|
| `StixDBEngine` | Orchestration, lifecycle, and global config. |
| `MemoryGraph` | Unified API for graph topology and vector search. |
| `MemoryAgent` | Autonomous background "janitor" per collection. |
| `ContextBroker` | Smart query routing and multi-phase retrieval. |
| `Reasoner` | LLM synthesis and citation engine. |

For visual flow diagrams, see [ARCHITECTURE_DIAGRAMS.md](file:///d:/StixDB/doc/ARCHITECTURE_DIAGRAMS.md).

---

## 2. The Memory Model

Memory in StixDB is stored as a **directed, typed graph**. Each piece of information is a `MemoryNode`, connected by `RelationEdges`.

### Memory Node Structure

Every node contains:
- **Content**: The raw text or data.
- **Node Type**: `fact`, `entity`, `event`, `concept`, `procedure`, `summary`.
- **Tier**: `working`, `episodic`, `semantic`, `procedural`, `archived`.
- **Importance**: A float (0-1) used for pruning and ranking.
- **Embedding**: A vector representation for semantic search.
- **Lineage**: Metadata tracking the original source (PDF page, file offset, parent nodes).

### The Tiering System

StixDB manages memory longevity through tiers:
1. **Working Memory**: "Hot" nodes that are frequently accessed. They receive a ranking boost during retrieval.
2. **Episodic Memory**: Recent information that hasn't been generalized yet.
3. **Semantic Memory**: Generalized knowledge, often the result of agent-driven consolidation.
4. **Procedural Memory**: Knowledge about "how things work" (skills and processes).
5. **Archived Memory**: "Cold" nodes eligible for pruning if they lack importance or access.

---

## 3. Autonomous Maintenance

Unlike passive databases, StixDB actively manages its own data through the `MemoryAgent`.

### The Maintenance Loop
The agent runs a `perceive → plan → act` cycle on a configurable interval (default: 60s).

1. **Access Planning**: It tracks how often nodes are accessed via the `ContextBroker`. Hot nodes are promoted to `working`, while unused nodes are demoted to `archived`.
2. **Semantic Consolidation**: It looks for pairs of nodes with a cosine similarity above a threshold (e.g., 0.88). If found, it:
    - Creates a new `SUMMARY` node.
    - Connects the summary to the originals via `DERIVED_FROM` edges.
    - Demotes the original nodes to `archived`.
3. **Pruning**: It deletes `archived` nodes whose importance (decayed over time) falls below a threshold (e.g., 0.1).
4. **Lineage Safety**: If `STIXDB_AGENT_LINEAGE_SAFE_MODE=true`, it pins original source nodes used in summaries to prevent them from being pruned, preserving the provenance chain.

---

## 4. Query & Retrieval Pipeline

The `ContextBroker` implements a **7-phase retrieval pipeline** to ensure answering is grounded and contextual.

1. **Embed**: The query is embedded using the configured embedding model.
2. **Vector Search**: Fast semantic lookup to find "seed nodes."
3. **Graph Expansion**: BFS traversal from seeds (default depth=2) to find related context that might not match semantically but is relevant by connection.
4. **Tier Boost**: `working` memory nodes get a score bonus.
5. **Truncation**: Results are ranked and truncated to fit the LLM's context window.
6. **Synthesis**: The `Reasoner` (LLM) generates an answer + a step-by-step reasoning trace.
7. **Recording**: Access counts are updated to inform the next agent cycle.

---

## 5. Storage & Backends

StixDB decouples graph topology from vector search, allowing flexible deployments.

### Graph Backends
- **Memory (NetworkX)**: Ephemeral, in-process. Perfect for learning and testing. Data lost on exit.
- **KuzuDB**: Persistent on disk, no Docker. **Recommended for local development.** Data survives restarts.
- **Neo4j**: Production-scale persistence via Docker. Multi-agent, audit trails, backups.

### Vector Backends
- **Memory (Numpy)**: Direct in-memory similarity.
- **Chroma**: Local vector database for medium-scale apps.
- **Qdrant**: High-performance, distributed vector search.

---

## 6. API & Integration

### Python Engine API
Directly import `StixDBEngine` for in-process application use.
```python
from stixdb import StixDBEngine, StixDBConfig

async with StixDBEngine(StixDBConfig()) as engine:
    await engine.store("agent_1", "Project deadline is June 1st", tags=["roadmap"])
    response = await engine.ask("agent_1", "When is the project deadline?")
```

### REST API
Start a standalone server: `stixdb serve --port 8080`.
- `/collections/{id}/ask`: Grounded question answering.
- `/v1/chat/completions`: OpenAI-compatible interface.
- `/search`: Multi-query, cross-collection search.

### Python SDK
A lightweight client that wraps the REST API.
```python
from stixdb_sdk import StixDBClient

client = StixDBClient(base_url="http://localhost:8080")
client.memory.store("demo", "StixDB is agentic memory.")
```

---

## 7. Performance & Observability

StixDB includes built-in observability:
- **Traces**: Inspect precisely what the agent "thought" during consolidation via `GET /traces`.
- **Metrics**: Prometheus-compatible metrics for node counts, latency, and agent cycle health.
- **Logs**: Structured logs (via `structlog`) for deep debugging.

---

## Conclusion

StixDB moves the complexity of memory management and context synthesis **inside** the database. This allows application developers to build agents that are smarter, more efficient, and inherently more capable of reasoning over their own history.

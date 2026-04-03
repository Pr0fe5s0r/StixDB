<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" />
  <a href="https://pypi.org/project/stixdb-engine/"><img src="https://img.shields.io/pypi/v/stixdb-engine?style=flat-square&label=stixdb-engine" /></a>
  <a href="https://pypi.org/project/stixdb-sdk/"><img src="https://img.shields.io/pypi/v/stixdb-sdk?style=flat-square&label=stixdb-sdk" /></a>
  <img src="https://img.shields.io/github/actions/workflow/status/your-org/stixdb/ci.yml?style=flat-square&label=CI" />
  <img src="https://img.shields.io/badge/LLM-OpenAI%20%7C%20Anthropic%20%7C%20Ollama-purple?style=flat-square" />
  <img src="https://img.shields.io/badge/API-Search%20%7C%20Ask%20%7C%20OpenAI--compat-orange?style=flat-square" />
</p>

<h1 align="center">StixDB — Living Memory for AI Agents</h1>

<p align="center"><b>Stop shoving documents into filing cabinets. Give your agent an Autonomous Librarian.</b></p>

<p align="center">
  StixDB exposes a <b>Search API</b> and an <b>Ask API</b> over your private knowledge —<br/>
  documents, agent memories, ingested data — with the same interface shape as Perplexity:<br/>
  ranked results from Search, grounded cited answers from Ask.<br/><br/>
  Under the hood every collection runs an autonomous agent that continuously<br/>
  reorganises memory, merges duplicates, decays stale facts, and reasons over a live graph.
</p>

---

## StixDB = Private Perplexity for Your Data

Perplexity's Sonar API searches the live web and returns cited answers.
**StixDB does the same for your private knowledge base.**

| | Perplexity Sonar | StixDB |
|---|---|---|
| **Data source** | Live web | Your documents, memories, agent data |
| **Search API** | Web search → ranked results | `/search` → ranked nodes across collections |
| **Ask API** | Web context → cited LLM answer | `/ask` → graph-grounded cited LLM answer |
| **Citations** | Source URLs | Source nodes with content, tier, score |
| **Memory** | Stateless | Self-organising graph — decays, merges, promotes |
| **Streaming** | ✅ | ✅ `/chat/completions` with `"stream": true` |
| **OpenAI-compat** | ❌ | ✅ Drop-in at `POST /chat/completions` |
| **Private / on-prem** | ❌ | ✅ Fully self-hosted |
| **Requires API key** | Yes (`pplx-…`) | **Search API: No — Ask API: Yes (any LLM provider)** |
| **Requires Docker** | N/A | **No — `pip install stixdb-engine` is enough to start** |

### The two APIs

**Search API** — fast ranked retrieval, no LLM:

```bash
# Perplexity style: search your private data
POST /search
{
  "query": "What are the upcoming project deadlines?",
  "collections": ["project", "team"],
  "max_results": 5
}

# Response: ranked nodes with scores, tiers, and source lineage
```

**Ask API** — grounded, cited answers:

```bash
# Ask your private knowledge base
POST /collections/project/ask
{
  "question": "Who is responsible for the payments deadline?",
  "top_k": 10
}

# Response: synthesised answer + citations + confidence + reasoning trace
{
  "answer": "Alice (lead engineer, payments team) owns the June 1st deadline.",
  "confidence": 0.93,
  "sources": [
    { "content": "Alice is the lead engineer on the payments team", "score": 0.96 },
    { "content": "Project deadline is June 1st, 2026", "score": 0.91 }
  ]
}
```

**OpenAI-compatible endpoint** — drop in anywhere:

```bash
POST /chat/completions
{
  "model": "project",        # collection name becomes the model
  "messages": [{ "role": "user", "content": "What are the upcoming milestones?" }],
  "stream": true
}
```

Works out of the box with the OpenAI Python SDK, LangChain `ChatOpenAI`, or any tool that speaks the OpenAI spec — just point `base_url` at your StixDB instance.

---

## Stop Shoving Documents into Filing Cabinets

Standard RAG is a mess of duplicates and stale facts. You shove documents in, retrieve the nearest neighbors, and hope the LLM stitches them into something useful.

```
Traditional RAG:

  User Question
       │
       ▼
  [Vector Search]  ──→  top-k chunks (static, never changes)
       │
       ▼
  [LLM Prompt]     ──→  answer (no memory of what was useful)
```

The filing cabinet never organises itself. Stale facts stay forever. Duplicates pile up. Hot information gets no priority over cold. Nothing learns from access patterns.

**StixDB is an Autonomous Librarian.**

```
StixDB:

  User Question
       │
       ▼
  [7-Phase Retrieval]  ──→  contextual answer + reasoning trace + cited sources
       │
       ▲
  [Living Memory Graph]
       │
  ┌────┴──────────────────────────────────────────────┐
  │  MemoryAgent (runs every 30 seconds)               │
  │                                                    │
  │  PERCEIVE  ──  track which nodes are accessed      │
  │  PLAN      ──  score heat: 0.6×frequency +         │
  │                            0.4×recency             │
  │  ACT       ──  promote hot nodes → working memory  │
  │                merge semantically similar nodes    │
  │                decay importance by half every 48h  │
  │                prune nodes below 0.05 importance   │
  └────────────────────────────────────────────────────┘
```

---

## What Makes StixDB Different

| Capability | Traditional RAG | StixDB |
|---|---|---|
| Retrieval | Vector similarity | 7-phase: vector → graph BFS → tier-aware re-rank → LLM reason |
| Memory structure | Flat chunks | Typed graph nodes with edges and clusters |
| Stale data | Stays forever | Exponential decay (`importance × 2^(-t/48h)`) |
| Duplicates | Pile up | Auto-merged when cosine similarity > 0.88 |
| Hot vs cold | No concept | 5 tiers: `working → episodic → semantic → procedural → archived` |
| Access patterns | Ignored | LRU+LFU hybrid heat scoring drives tier promotion |
| Answers | Raw chunks | LLM synthesis with citations and reasoning trace |
| Background work | None | Autonomous `perceive → plan → act` loop per collection |
| Source lineage | Lost on re-chunk | Preserved across merges (`parent_node_ids`, char offsets) |
| LLM dependency | Required | Optional — heuristic mode works with no API key |

---

## Getting Started

**Local development (no Docker):**
```bash
pip install "stixdb-engine[local-dev]"
```

See [QUICKSTART.md](QUICKSTART.md) for a complete guide to building agent memory on your laptop.

**Production (Docker):**
```bash
docker compose up -d
```

See [PRODUCTION.md](PRODUCTION.md) for scaling, multi-agent deployments, and operations.

---

## How It Works

### Memory Node Types

```
fact        →  "Project deadline is June 1st, 2026"
entity      →  "Alice — lead engineer, payments team"
event       →  "Sprint review on April 10th"
concept     →  "Payments module uses event-sourcing pattern"
procedure   →  "How to deploy to production"
summary     →  [auto-generated merge of related facts]
question    →  "What are the upcoming deadlines?"  (cached answers)
```

### Memory Tiers

```
working     ─── hot, frequently accessed  ← +0.15 retrieval boost
episodic    ─── recent, not yet generalised
semantic    ─── generalised knowledge (often from consolidation)
procedural  ─── skills and how-to sequences
archived    ─── cold, eligible for pruning
```

The agent automatically promotes and demotes nodes based on access heat.

### The 7-Phase Retrieval Pipeline

```
1. Embed Query       →  384-dim vector for the question
2. Vector Search     →  top-15 semantic candidates (threshold: 0.25)
3. Graph BFS         →  expand to neighbours (depth 2)
4. Tier Re-rank      →  working memory nodes get +0.15 score boost
5. Truncate          →  keep top 20 nodes by combined score
6. LLM Reason        →  synthesise answer with citations
7. Record & Trace    →  update access counts, emit telemetry
```

### The Background Agent Cycle (every 30 seconds)

```python
# PERCEIVE
access_data = planner.collect_access_patterns()

# PLAN — hybrid heat score
heat = 0.6 * frequency_score   # saturates at 10 accesses/24h
     + 0.4 * recency_score     # half-life: 12 hours

# ACT
if heat > 0.65:  promote → working memory
if decay < 0.08: demote  → archived
if similarity(node_a, node_b) > 0.88:  merge → summary node
if importance < 0.05 and tier == archived:  prune permanently
```

---

## RAG vs StixDB — Side by Side

### Scenario: A month of project updates ingested

**RAG after 30 days**

```python
results = vector_db.search("project status", top_k=5)
# Returns 5 chunks, including:
# - "Sprint 1 complete" (from day 1 — stale, never removed)
# - "Sprint 1 complete" (duplicate, from a different doc format)
# - "Sprint 2 in progress" (from week 2 — outdated)
# - "Sprint 4 kicked off" (current)
# - "Alice joined the team" (relevant)
#
# No synthesis. No ranking by freshness. No deduplication.
# The LLM now has contradictory context and must figure it out.
```

**StixDB after 30 days**

```python
response = await engine.ask("my_agent", "What is the project status?")
# Working memory (tier=working, heat=0.91):
#   → "Sprint 4 kicked off — focus is payments integration"
#   → "Alice is leading sprint 4 delivery"
#
# Auto-merged:
#   → "Sprint 1 complete" + "Sprint 1 done" → single summary node (archived)
#
# Decayed and pruned:
#   → "Sprint 2 in progress" — importance=0.03, pruned at day 22
#
# Response:
#   answer: "Sprint 4 is currently active, focused on payments integration.
#            Alice is leading delivery."
#   sources: [cited working-memory nodes]
#   reasoning_trace: [step-by-step]
```

---

## Architecture

```
StixDBEngine
├── MemoryGraph          — unified graph + vector interface
│   ├── StorageBackend   — graph topology (NetworkX / KuzuDB / Neo4j)
│   └── VectorStore      — semantic search (NumPy / ChromaDB / Qdrant)
│
├── MemoryAgent          — per-collection autonomous agent
│   ├── AccessPlanner    — LRU+LFU heat scoring → tier promotion
│   ├── Consolidator     — cosine merge (0.88) + decay + prune (0.05)
│   └── MemoryAgentWorker— async background loop (APScheduler)
│
├── ContextBroker        — 7-phase retrieval + LLM reasoning
│   └── Reasoner         — OpenAI / Anthropic / Ollama / Custom / None
│
└── FastAPI Server       — REST API + OpenAI-compatible endpoint
```

---

## Storage & Vector Backends

### Graph Storage

| Backend | Mode | Use Case | Install |
|---------|------|----------|---------|
| NetworkX | `memory` | Learning / testing — data lost on exit | Included |
| KuzuDB | `kuzu` | Local development — persistent on disk | `pip install stixdb-engine[local-dev]` |
| Neo4j | `neo4j` | Production — scalable with Docker | `pip install stixdb-engine[neo4j]` |

### Vector Search

| Backend | Scale | Install |
|---------|-------|---------|
| NumPy | Up to ~500k nodes | Included |
| ChromaDB | Medium scale | `pip install stixdb-engine` (included) |
| Qdrant | Billion-scale | `pip install stixdb-engine[qdrant]` |

### LLM Providers

```python
LLMProvider.OPENAI     # gpt-4o, gpt-4-turbo, ...
LLMProvider.ANTHROPIC  # claude-3-5-sonnet, claude-3-opus, ...
LLMProvider.OLLAMA     # llama3, mistral, phi3, ... (local)
LLMProvider.CUSTOM     # any OpenAI-compatible endpoint
LLMProvider.NONE       # heuristic mode — no API key needed
```

### Embedding Providers

```python
EmbeddingProvider.SENTENCE_TRANSFORMERS  # all-MiniLM-L6-v2, local, free
EmbeddingProvider.OPENAI                 # text-embedding-3-small/large
EmbeddingProvider.OLLAMA                 # nomic-embed-text, local
EmbeddingProvider.CUSTOM                 # any OpenAI-compatible endpoint
```

---

## API & SDK

StixDB exposes:

- **REST API**: HTTP endpoints for store, retrieve, ask, upload, agent inspection
- **OpenAI-compatible endpoint**: `/v1/chat/completions` for drop-in replacement
- **Python SDK**: `stixdb-sdk` — sync and async clients

Full API reference and examples:
- See [QUICKSTART.md](QUICKSTART.md) for local development examples
- See [PRODUCTION.md](PRODUCTION.md) for deployment, scaling, and monitoring

---

## Resources

- **[QUICKSTART.md](QUICKSTART.md)** — Build agent memory on your laptop (local development)
- **[PRODUCTION.md](PRODUCTION.md)** — Deploy with Docker for scaling and multi-agent
- **[Cookbooks](cookbooks/)** — Runnable examples for all SDK patterns
- **[Architecture Docs](doc/)** — Deep dives into design and performance
- **[Contributing](CONTRIBUTING.md)** — How to contribute to the project

---

## Development

### Running tests

```bash
pip install stixdb-engine[dev]
pytest tests/ -v
```

### Building the SDK

```bash
pip install build twine
python -m build
```

---

## Project Layout

```
stixdb/             Core engine (graph, agent, broker, API)
sdk/                Lightweight Python HTTP client (stixdb-sdk)
examples/           Runnable examples (core, agents, search, OpenAI-compat)
demos/              Standalone sandboxes for experimentation
scripts/            Benchmarks, debug helpers, manual test clients
doc/                Architecture and performance documentation
tests/              Automated test suite
```

---

### One-time setup

**1. Create a PyPI account**

Register at [pypi.org](https://pypi.org) and create an API token:
`Account settings → API tokens → Add API token` (scope: entire account for first upload, then per-project).

**2. Configure trusted publishing (recommended — no stored secrets)**

In your GitHub repo go to `Settings → Environments → New environment` and name it `pypi`.

Then on PyPI go to your project page → `Settings → Publishing` and add a trusted publisher:
- Owner: `your-org`
- Repository: `stixdb`
- Workflow: `publish-sdk.yml`
- Environment: `pypi`

This lets GitHub Actions publish without storing an API key anywhere.

**3. Install build tools locally**

```bash
pip install build twine hatch
```

---

### Publishing `stixdb-sdk`

**Manual publish (first time or hotfix)**

```bash
cd sdk

# Bump the version in sdk/pyproject.toml, then:
python -m build                  # creates dist/stixdb_sdk-x.y.z.tar.gz and .whl
twine check dist/*               # verify the package is valid
twine upload dist/*              # uploads to PyPI — prompts for token
```

**Automated publish via GitHub Actions**

```bash
# Bump version in sdk/pyproject.toml, commit, then tag:
git tag sdk-v0.2.0
git push origin sdk-v0.2.0
# The publish-sdk.yml workflow triggers automatically
```

---

### Publishing `stixdb-engine`

```bash
# From the repo root:
python -m build                  # creates dist/ from root pyproject.toml
twine check dist/*
twine upload dist/*
```

Add a `publish-engine.yml` workflow following the same pattern as `publish-sdk.yml`
(trigger on tags matching `engine-v*`).

---

### Version bump checklist

- [ ] Update `version` in `sdk/pyproject.toml` (for SDK releases)
- [ ] Update `version` in `pyproject.toml` (for engine releases)
- [ ] Update `__version__` in `sdk/src/stixdb_sdk/__init__.py`
- [ ] Update `__version__` in `stixdb/__init__.py`
- [ ] Add a `CHANGELOG.md` entry
- [ ] Tag the commit and push

---

## Contributing

We welcome contributions of all kinds — bug reports, features, docs, examples.

See [CONTRIBUTING.md](CONTRIBUTING.md) to get started.

If you find a security issue, see [SECURITY.md](SECURITY.md).

---

## License

MIT — see [LICENSE](LICENSE).

---

<p align="center">
  <i>Built with the vision of making AI agents smarter through intelligent, autonomous memory.</i>
</p>

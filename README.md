<p align="center">
  <img src="assets/stix_logo.png" alt="StixDB Logo" width="200" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" />
  <a href="https://pypi.org/project/stixdb-engine/"><img src="https://img.shields.io/pypi/v/stixdb-engine?style=flat-square&label=stixdb-engine" /></a>
  <a href="https://pypi.org/project/stixdb-sdk/"><img src="https://img.shields.io/pypi/v/stixdb-sdk?style=flat-square&label=stixdb-sdk" /></a>
  <img src="https://img.shields.io/badge/LLM-OpenAI%20%7C%20Anthropic%20%7C%20Ollama-purple?style=flat-square" />
</p>

<h1 align="center">StixDB — Living Memory for AI Agents</h1>

<p align="center"><b>A self-organizing memory database for AI agents. Stores facts, cleans up stale data automatically, and answers questions with citations.</b></p>

---

## What is StixDB?

When you build an AI agent, it needs somewhere to remember things. You could use a simple vector database — but that's like a filing cabinet that **never gets tidied**. Stale facts pile up, duplicates accumulate, and the agent has no way to know what's fresh vs. what's a month old.

StixDB is different. Every collection of memories has a built-in **background agent** that continuously organizes data: merging near-duplicate facts, decaying things you haven't looked at in days, and promoting frequently-accessed knowledge to the front of the queue.

---

## Quick Start (No API Keys Needed!)

Install:
```bash
pip install "stixdb-engine[local-dev]"
```

Run (completely local — no API key, no cloud, no Docker):
```python
import asyncio
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import StorageConfig, StorageMode, ReasonerConfig, LLMProvider

async def main():
    config = StixDBConfig(
        storage=StorageConfig(mode=StorageMode.KUZU, kuzu_path="./my_db"),
        reasoner=ReasonerConfig(provider=LLMProvider.NONE),  # No API key needed
    )
    async with StixDBEngine(config=config) as engine:
        await engine.store("my_agent", "Alice is the lead engineer on payments.")
        await engine.store("my_agent", "Project deadline is June 1st, 2026.")

        results = await engine.retrieve("my_agent", "Who leads the payments team?")
        for r in results:
            print(r['content'])

asyncio.run(main())
```

---

## How the Three Modes Work

### Mode 1 — No API Key (Heuristic Search)
`LLMProvider.NONE` activates **heuristic mode**. You can still store and search memories — you just don't get AI-synthesized answers.

**Exactly what it does:** The engine retrieves the top-K semantically similar nodes using **cosine similarity** on 384-dim sentence embeddings, then re-ranks them by their `importance` score. The result is an ordered list of matching facts — fast, accurate, and completely free.

```python
# Returned results (no LLM synthesis, just ranked matches):
results = await engine.retrieve("my_agent", "payment deadline")
# [{"content": "Project deadline is June 1st", "score": 0.91, ...}, ...]
```

### Mode 2 — With an LLM API Key (Full Reasoning)
Add `OPENAI_API_KEY` (or Anthropic/Ollama) and unlock `ask()` and `chat()`. The engine now synthesizes a natural-language answer **with cited sources** using the 7-phase retrieval pipeline.

```python
# Set key once in your terminal: export OPENAI_API_KEY=sk-...
config = StixDBConfig(
    reasoner=ReasonerConfig(provider=LLMProvider.OPENAI, model="gpt-4o"),
)
async with StixDBEngine(config=config) as engine:
    response = await engine.ask("my_agent", "Who owns the June deadline?")
    print(response.answer)          # "Alice, lead engineer on payments."
    print(response.reasoning_trace) # Step-by-step: why it chose those facts
    print(response.confidence)      # 0.93
```

### Mode 3 — Standalone Server + SDK
Start a server and connect via the Python SDK (good for microservices or multiple processes):

```bash
stixdb serve --port 4020
```
```python
from stixdb_sdk import StixDBClient
with StixDBClient("http://localhost:4020") as client:
    client.memory.store("my_agent", content="Alice leads payments.")
    client.memory.ingest_folder("my_agent", folder_path="./docs")
    answer = client.query.ask("my_agent", question="Who leads payments?")
```

---

## The Background Agent — What It Actually Does

Every 30 seconds (configurable), a background cycle runs per collection. Here's **exactly** what happens:

### Step 1: Merge near-duplicate facts (Pairwise cosine similarity)
It loads a batch of up to 64 episodic + semantic nodes (`max_consolidation_batch`), computes pairwise cosine similarity between their embeddings, and merges any pair that exceeds **0.88 similarity** (configurable, default `consolidation_similarity_threshold=0.88`).

A merged pair becomes a new `[SUMMARY]` node whose embedding is the normalized average of the two originals. **The originals are archived (not deleted)** and flagged with `lineage_preserved=True` so you can always trace where a summary came from.

### Step 2: Remove exact duplicates (Hash-based deduplication)
Nodes with identical content hashes (`content_hash`) or identical document chunk hashes (`document_hash:chunk_index`) are deduplicated — only the highest-tier, highest-importance copy is kept.

### Step 3: Decay and prune cold nodes (Exponential decay)
Each archived node's importance score decays with a half-life of **48 hours** (configurable, `decay_half_life_hours=48`):

```
decay_score = importance × 2^(-(hours_since_access / 48))
```

Nodes with `decay_score < 0.05` (configurable, `prune_importance_threshold=0.05`) that are **not pinned** are permanently deleted.

### What's the CPU cost?
The cycle processes a maximum of 64 nodes (`max_consolidation_batch=64`) per run. All comparisons are in-process NumPy operations. On a typical laptop:
- **10–100 nodes**: cycle takes ~5–20ms
- **1,000 nodes**: cycle takes ~100–300ms (pairwise on the 64-node batch, not all 1,000)
- **100,000 nodes**: cycle still processes the same 64-node batch — **the batch size caps CPU cost**

The cycle runs in the background on an async loop and **does not block your queries**.

---

## Scale Expectations (Honest Numbers)

StixDB uses an in-process NumPy cosine search by default. Here's what to expect:

| Node Count | Vector Search Latency | Background Cycle | Storage Backend |
|---|---|---|---|
| ~100 | < 1ms | ~5ms | In-memory (default) |
| ~10,000 | ~5–15ms | ~50–100ms | KuzuDB recommended |
| ~100,000 | ~50–150ms | ~150ms (capped batch) | KuzuDB or Neo4j |
| > 500,000 | Switch to Qdrant | ~150ms (capped) | Neo4j + Qdrant |

The background agent's **batch cap** (`max_consolidation_batch=64`) means it never processes your entire graph at once — it samples a representative slice. This keeps cycle time predictable regardless of total node count.

---

## Configuration Quick Reference

All settings read from environment variables or a `.env` file:

```bash
# LLM (optional — for ask() and chat())
STIXDB_LLM_PROVIDER=openai         # openai | anthropic | ollama | none
OPENAI_API_KEY=sk-...

# Storage (default: in-memory, lost on restart)
STIXDB_STORAGE_MODE=kuzu           # memory | kuzu (persistent) | neo4j
STIXDB_KUZU_PATH=./my_db

# Background agent tuning
STIXDB_AGENT_CYCLE_INTERVAL=30.0           # How often the cycle runs (seconds)
STIXDB_AGENT_CONSOLIDATION_THRESHOLD=0.88  # Merge similar nodes above this cosine score
STIXDB_AGENT_DECAY_HALF_LIFE=48.0          # Hours before an unused node halves in importance
STIXDB_AGENT_PRUNE_THRESHOLD=0.05          # Delete node if importance falls below this

# Server
STIXDB_API_PORT=4020
STIXDB_API_KEY=your-secret-key             # Optional — auth for the REST API
```

Load in code with one line:
```python
config = StixDBConfig.from_env()
```

---

## Ingesting Documents

```python
# Single PDF (uses pypdf, preserves page numbers in metadata)
await engine.ingest_file("my_agent", filepath="./manual.pdf", tags=["docs"])

# Entire folder (recursive, auto-detects .pdf, .md, .txt, .json, .py, etc.)
await engine.ingest_folder("my_agent", folderpath="./docs", recursive=True)
```

Deduplication is built-in: ingesting the same file twice will not create duplicate chunks (hashed at the chunk level).

---

## Storage Backends

| Backend | Install | Persistence | Best For |
|---|---|---|---|
| **In-Memory (NumPy)** | Included | ❌ Lost on restart | Testing, prototypes |
| **KuzuDB** | `pip install "stixdb-engine[local-dev]"` | ✅ On-disk | Local dev, laptops |
| **Neo4j + Qdrant** | Docker | ✅ Production | High scale, multi-agent |

---

## Go Deeper

- **[QUICKSTART.md](QUICKSTART.md)** — Step-by-step guide from zero to a working agent memory.
- **[cookbooks/](cookbooks/)** — Runnable examples: PDF chat, LangChain RAG, multi-agent, OpenAI-compat.
- **[PRODUCTION.md](PRODUCTION.md)** — Docker deployment and operations.
- **[DEVELOPMENT.md](DEVELOPMENT.md)** — Build, test, and publish guide for contributors.

---

## License

MIT — see [LICENSE](LICENSE).

<p align="center">
  <i>AI agents deserve better than flat files. Give yours a living memory.</i>
</p>

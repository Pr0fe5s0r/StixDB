<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" />
  <img src="https://img.shields.io/badge/async-httpx-orange?style=flat-square" />
</p>

# stixdb-sdk — Python Client for StixDB

Lightweight, ergonomic Python client for the [StixDB Agentic Context Database](../README.md). Covers the full REST API surface in both synchronous and asynchronous flavours.

> **Tip:** Use `stixdb-sdk` for memory management, ingestion, search, and Q&A.
> For streaming chat or drop-in OpenAI replacement, use the standard `openai` client
> pointed at `http://your-stix-server/v1` (see [OpenAI Compatibility](#openai-compatibility)).

---

## Installation

```bash
pip install stixdb-sdk
```

Or from source:

```bash
pip install -e sdk/   # from the repo root
```

Requires Python 3.10+ and a running StixDB server (`stixdb serve --port 4020`).

---

## Quick Start

```python
from stixdb_sdk import StixDBClient

with StixDBClient(base_url="http://localhost:4020", api_key="your-key") as client:

    # Store a memory
    client.memory.store("my_agent", content="Launch is June 1st, 2026",
                        node_type="fact", tags=["deadline"], importance=0.9)

    # Ingest a whole folder of documents
    client.memory.ingest_folder("my_agent", folder_path="./docs", recursive=True)

    # Search — ranked, filterable, no LLM needed
    results = client.search.create("launch deadline", collection="my_agent", max_results=5)
    for hit in results["results"]:
        print(f"[{hit['score']:.3f}] {hit['snippet']}")

    # Ask — LLM reasoning over the graph
    answer = client.query.ask("my_agent", question="When is the launch and who owns it?")
    print(answer["answer"])
    print(answer["reasoning_trace"])
```

---

## Client Initialisation

```python
from stixdb_sdk import StixDBClient, AsyncStixDBClient

# Sync
client = StixDBClient(
    base_url="http://localhost:4020",  # default
    api_key="your-key",               # sets Authorization: Bearer <key>
    timeout=60.0,                     # request timeout in seconds
)

# Async
client = AsyncStixDBClient(
    base_url="http://localhost:4020",
    api_key="your-key",
    timeout=60.0,
)

# Both support context managers
with StixDBClient(...) as client:
    ...

async with AsyncStixDBClient(...) as client:
    ...
```

---

## Memory — `client.memory`

### `store` — Add a single node

```python
result = client.memory.store(
    collection="my_agent",
    content="Alice is the lead engineer on the payments team.",
    node_type="entity",          # fact | entity | event | concept | procedure | summary
    tier="episodic",             # working | episodic | semantic | procedural | archived
    importance=0.8,              # 0.0 – 1.0; affects retrieval ranking and decay
    source="onboarding-doc.pdf", # optional provenance label
    tags=["team", "payments"],
    metadata={"department": "engineering"},
    pinned=False,                # True = never pruned by the background agent
)
print(result["id"])  # UUID of the new node
```

### `bulk_store` — Add many nodes in one call

```python
items = [
    {"content": "Sprint 4 kicked off", "node_type": "event", "tags": ["sprint"]},
    {"content": "Payments module uses event sourcing", "node_type": "concept"},
]
result = client.memory.bulk_store("my_agent", items=items)
print(f"Stored {result['stored']} nodes")
```

### `upload` — Upload a single file

Supported: `.pdf`, `.txt`, `.md`, `.json`, `.yaml`, `.py`, `.js`, `.ts`, `.csv`, `.sql` and more.

```python
result = client.memory.upload(
    collection="my_agent",
    file_path="./roadmap.pdf",
    tags=["roadmap", "planning"],
    chunk_size=1000,     # characters per chunk
    chunk_overlap=200,   # overlap between chunks
    parser="auto",       # auto | legacy | docling
)
print(f"Ingested {result['chunks_created']} chunks from {result['filename']}")
```

PDF ingestion preserves **page-level provenance** — each chunk stores its source page number in metadata.

### `ingest_folder` — Upload an entire directory

```python
result = client.memory.ingest_folder(
    collection="docs",
    folder_path="./knowledge_base",
    recursive=True,
    tags=["v2-docs"],
    chunk_size=1000,
    chunk_overlap=200,
    parser="auto",
)
print(f"Processed {result['files_processed']} files, {result['chunks_created']} chunks")
```

### `list` — List nodes in a collection

```python
nodes = client.memory.list(
    collection="my_agent",
    tier="working",           # filter by tier (optional)
    node_type="fact",         # filter by type (optional)
    limit=50,
    offset=0,
)
for node in nodes:
    print(node["content"], node["tier"], node["importance"])
```

### `get` — Retrieve a single node by ID

```python
node = client.memory.get("my_agent", node_id="uuid-here")
print(node["content"], node["decay_score"], node["access_count"])
```

### `delete` — Delete a single node

```python
client.memory.delete("my_agent", node_id="uuid-here")
```

### `delete_collection` — Wipe an entire collection

```python
client.memory.delete_collection("temp_experiments")  # irreversible
```

---

## Query — `client.query`

### `ask` — Agentic Q&A with LLM reasoning

Runs the full 7-phase retrieval pipeline: embed → vector search → graph BFS → re-rank → truncate → LLM reason → record.

```python
response = client.query.ask(
    collection="my_agent",
    question="Who should I contact about the payments deadline?",
    top_k=15,         # max semantic candidates
    threshold=0.25,   # minimum cosine similarity
    depth=2,          # graph BFS depth from seed nodes
)

print(response["answer"])
# → "Alice, lead engineer on the payments team. Deadline is June 1st, 2026."

print(response["confidence"])          # 0.0 – 1.0
print(response["reasoning_trace"])     # step-by-step reasoning
for source in response["sources"]:
    print(source["content"], source["tier"], source["score"])
```

With a custom system prompt and structured output:

```python
response = client.query.ask(
    collection="my_agent",
    question="Summarise all deadlines as a JSON list",
    system_prompt="You are a project management assistant. Be concise.",
    output_schema={"type": "array", "items": {"type": "string"}},
)
```

### `retrieve` — Raw retrieval, no LLM

Returns ranked nodes without generating an answer. Use this when you want to feed context into your own pipeline.

```python
nodes = client.query.retrieve(
    collection="my_agent",
    query="upcoming deadlines",
    top_k=10,
    threshold=0.25,
    depth=1,
)
for node in nodes:
    print(f"[{node['score']:.3f}] {node['content']}")
```

---

## Search — `client.search`

Product-style search across one or more collections — no LLM, just ranked results.

### Basic search

```python
results = client.search.create(
    query="project deadline",
    collection="my_agent",
    max_results=5,
)
for hit in results["results"]:
    print(f"[{hit['score']:.3f}] {hit['snippet']}")
```

### Multi-query, cross-collection

```python
results = client.search.create(
    query=["launch deadline", "team contacts"],   # multiple queries
    collections=["project", "hr"],                # multiple collections
    max_results=5,
)
# results["results"] is grouped by query, in order
```

### Filtering

```python
results = client.search.create(
    query="climate risk analysis",
    collection="research",
    max_results=10,
    # Source filtering
    source_filter=["paper.pdf", "briefing.md"],  # allowlist
    # source_filter=["-slack-export.json"],       # denylist (prefix with -)
    # Node filtering
    tag_filter=["climate", "risk"],
    node_type_filter=["fact", "summary"],
    tier_filter=["working", "episodic"],
    # Sizing
    max_chars_per_result=800,
    include_metadata=True,
)
```

### Heat-based ranking

```python
results = client.search.create(
    query="project status",
    collection="my_agent",
    sort_by="heat",          # relevance | heat | hybrid
    include_heatmap=True,    # adds recency, frequency, decay, temperature per result
)
for hit in results["results"]:
    print(hit["score"], hit.get("heatmap"))
```

---

## OpenAI Compatibility

StixDB exposes a `/v1` endpoint compatible with the OpenAI API. Use the standard `openai` library for streaming chat, or any tool that speaks the OpenAI protocol.

```python
from openai import OpenAI

# Point to your StixDB server
openai_client = OpenAI(
    base_url="http://localhost:4020/v1",
    api_key="your-stix-api-key",
)

# Collection name = model name
stream = openai_client.chat.completions.create(
    model="my_agent",
    messages=[{"role": "user", "content": "What are the upcoming milestones?"}],
    stream=True,
    extra_body={
        "thinking": True,   # show agent reasoning steps in the stream
        "verbose": True,    # show retrieval progress
    },
)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

List available collections as models:

```python
models = openai_client.models.list()
for m in models.data:
    print(m.id)
```

---

## Async Usage

```python
import asyncio
from stixdb_sdk import AsyncStixDBClient

async def main():
    async with AsyncStixDBClient(base_url="http://localhost:4020", api_key="your-key") as client:

        health = await client.health()
        print(health["status"])

        await client.memory.store("demo", content="Async is fast", node_type="fact")

        results = await client.search.create(
            ["launch deadline", "team contacts"],
            collections=["project", "hr"],
            max_results=5,
            sort_by="hybrid",
        )

        answer = await client.query.ask("project", question="When is the launch?")
        print(answer["answer"])

asyncio.run(main())
```

---

## Error Handling

The SDK uses `httpx` internally. All non-2xx responses raise `httpx.HTTPStatusError`.

```python
import httpx

try:
    client.query.ask("missing_collection", question="Hello?")
except httpx.HTTPStatusError as e:
    print(f"HTTP {e.response.status_code}: {e.response.text}")
```

---

## Full API Reference

| Namespace | Method | Description |
|-----------|--------|-------------|
| `client` | `health()` | Server health check |
| `client.memory` | `store(collection, content, ...)` | Add a single node |
| `client.memory` | `bulk_store(collection, items)` | Add many nodes |
| `client.memory` | `upload(collection, file_path, ...)` | Ingest a file |
| `client.memory` | `ingest_folder(collection, folder_path, ...)` | Ingest a directory |
| `client.memory` | `list(collection, ...)` | List nodes |
| `client.memory` | `get(collection, node_id)` | Get a single node |
| `client.memory` | `delete(collection, node_id)` | Delete a node |
| `client.memory` | `delete_collection(collection)` | Wipe a collection |
| `client.query` | `ask(collection, question, ...)` | Agentic Q&A |
| `client.query` | `retrieve(collection, query, ...)` | Raw retrieval |
| `client.search` | `create(query, collection, ...)` | Search |

All methods have async equivalents on `AsyncStixDBClient`.

---

## Related

- [StixDB Engine (server)](../README.md)
- [Architecture Guide](../doc/STIXDB_COMPREHENSIVE_GUIDE.md)
- [Examples](../sdk/examples/)

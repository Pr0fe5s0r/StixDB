---
name: engine-memory-layer
description: Use this skill whenever the user asks about using StixDBEngine directly for memory management, agentic context, reasoning, chat, streaming, or advanced memory operations. Covers engine.store(), engine.ask(), engine.chat(), engine.stream_chat(), engine.retrieve(), engine.ingest_file(), engine.recursive_chat(), engine.stream_recursive_chat(), and all other engine-level operations. Use when the user is working with the Python library (not the CLI or raw REST calls).
compatibility: Requires stixdb-engine Python package, Python 3.10+, a running StixDB server (stixdb daemon start), async/await support
---

# StixDB Engine API Skill

`StixDBEngine` is a REST client that connects to a running StixDB server and exposes a clean async Python API for all StixDB operations. It does **not** run anything in-process — all work is delegated to the server over HTTP.

> **Prerequisite:** start the server first with `stixdb daemon start` (or `stixdb serve`).

---

## Quick Start

```python
from stixdb import StixDBEngine, StixDBConfig

# Connect with defaults (localhost:4020, no auth)
engine = StixDBEngine()
await engine.store("my_agent", content="Alice leads the payments team.")
results = await engine.retrieve("my_agent", "payments lead", top_k=5)
response = await engine.ask("my_agent", "Who leads payments?")
print(response.answer)   # Markdown string with citations

# or use async context manager (recommended — ensures cleanup)
async with StixDBEngine() as engine:
    response = await engine.ask("my_agent", "Who leads payments?")
    print(response.answer)

# With explicit config
config = StixDBConfig(url="http://localhost:4020", api_key="your-key")
async with StixDBEngine(config=config) as engine:
    ...

# From environment variables
config = StixDBConfig.from_env()
async with StixDBEngine(config=config) as engine:
    ...
```

---

## Configuration

`StixDBConfig` holds only connection settings. The server manages all storage, LLM, and embedding config.

```python
from stixdb import StixDBConfig

config = StixDBConfig(
    url="http://localhost:4020",   # server base URL (default: http://localhost:4020)
    api_key="your-secret-key",     # must match STIXDB_API_KEY on server (optional)
    timeout=120.0,                 # HTTP timeout in seconds for non-streaming requests
)
```

**From environment (recommended):**

```python
config = StixDBConfig.from_env()
```

**Environment variables:**

```bash
STIXDB_URL=http://localhost:4020   # server URL
STIXDB_API_KEY=your-secret-key     # optional — must match server's STIXDB_API_KEY
STIXDB_TIMEOUT=120                 # HTTP timeout seconds (default 120)
```

**Inline construction (no config object needed):**

```python
engine = StixDBEngine(url="http://prod-server:4020", api_key="sk-...")
```

---

## Storing Memories

### `engine.store()`

```python
result = await engine.store(
    collection="agent_name",      # required — collection name
    content="The memory text.",   # required

    # Classification
    node_type="fact",             # fact | experience | goal | rule | pattern
    tier="episodic",              # episodic | semantic | procedural | working

    # Importance and lifecycle
    importance=0.7,               # 0.0 (ephemeral) → 1.0 (critical)
    pinned=False,                 # True = never pruned by decay

    # Metadata
    source="module_name",
    source_agent_id="worker_1",
    tags=["tag1", "tag2"],
    metadata={"custom": "value"},
    node_id="optional_custom_id", # auto-generated if omitted
)
# Returns: {"id": "uuid", "collection": "...", "status": "stored", ...}
```

**Importance guide:**

| Score | Use for |
|---|---|
| `0.95` | In-progress state, user preferences, critical decisions |
| `0.9` | Bug fixes, patterns, architecture rules |
| `0.85` | Module maps, API surfaces, session summaries |
| `0.7` | Normal facts (default) |
| `0.5` | Background / historical context |

### `engine.bulk_store()`

```python
items = [
    {"content": "Fact 1", "tier": "semantic", "importance": 0.8, "tags": ["a"]},
    {"content": "Fact 2", "tier": "episodic", "importance": 0.5},
]
result = await engine.bulk_store(collection="agent_name", items=items)
```

Each item accepts the same fields as `store()`. Use for batch imports and initialization.

---

## Ingesting Files

### `engine.ingest_file()`

```python
result = await engine.ingest_file(
    collection="agent_name",
    filepath="/path/to/document.pdf",
    tags=["docs", "v1"],
    chunk_size=600,       # characters per chunk (default 600)
    chunk_overlap=150,    # overlap between chunks (default 150)
)
# Returns: {"source_name": "...", "node_ids": [...], "ingested_chunks": N}
```

**Supported types:** `.pdf`, `.md`, `.rst`, `.html`, `.txt`, `.csv`, `.json`, `.jsonl`, `.yaml`, `.toml`, `.py`, `.js`, `.ts`, `.go`, `.rs`, `.sql`, and more. Binary files are skipped automatically.

Deduplication is built in — re-ingesting the same file doesn't create duplicate chunks.

### `engine.ingest_folder()`

```python
result = await engine.ingest_folder(
    collection="agent_name",
    folderpath="/path/to/docs",
    tags=["documentation"],
    chunk_size=600,
    chunk_overlap=150,
    recursive=True,
)
# Returns: {"files_processed": N, "files_skipped": N, "ingested": [...], "skipped": [...]}
```

Respects `.gitignore`. Skips `node_modules`, `.git`, and binary files automatically.

**Chunk size guidance:**
- Technical docs / code: `500–800`
- Prose / narrative: `1000–1500`
- Always keep overlap at ~20% of chunk size

---

## Retrieval

### `engine.retrieve()` — raw retrieval, no LLM

```python
nodes = await engine.retrieve(
    collection="agent_name",
    query="user preferences",
    top_k=10,
    threshold=0.1,        # minimum combined score (default 0.1)
    depth=1,              # graph expansion hops (default 1)
    mode="hybrid",        # "hybrid" (default) | "keyword" | "semantic"
)
# Returns: list of dicts, each with node fields + "score"
```

**Retrieval modes:**

| Mode | How it works | When to use |
|---|---|---|
| `"hybrid"` *(default)* | `0.7 × semantic_score + 0.3 × keyword_score` | Best general recall |
| `"keyword"` | Tag overlap + content term match. No embedding API call. ~5ms | Fast exact-term lookups |
| `"semantic"` | Vector embedding + cosine similarity | Paraphrase / conceptual queries |

Use `retrieve()` when you want ranked nodes without LLM cost. Use `ask()` when you need synthesis.

---

## Asking Questions (LLM Reasoning)

### `engine.ask()` — single-pass reasoning

```python
response = await engine.ask(
    collection="agent_name",
    question="What are the user's accessibility needs?",

    # Retrieval tuning
    top_k=15,
    threshold=0.2,
    depth=2,

    # LLM control
    thinking_steps=1,       # 1 = single-pass; 2+ = multi-hop reasoning
    hops_per_step=4,        # retrieval hops per thinking step
    system_prompt=None,     # override system instructions
    output_schema=None,     # enforce a JSON schema on the answer field
    max_tokens=None,        # cap LLM output; None = server default
)
```

**`ContextResponse` fields:**

```python
response.answer           # Markdown string — headers, bullets, inline citations [1][2], Sources section
response.reasoning_trace  # Internal chain-of-thought (not shown to user)
response.sources          # list[dict] — nodes used to generate the answer
response.confidence       # float 0–1, self-reported by the LLM
response.model_used       # e.g. "gpt-4o"
response.latency_ms       # end-to-end server latency in milliseconds
response.is_complete      # False when the LLM indicated it needs more information
response.suggested_query  # Optional follow-up search query suggested by the LLM

# Iterate sources
for src in response.sources:
    print(src["content"], src.get("relevance"))
```

**Answer format:** `ask()` returns rich Markdown with inline citations `[1]`, `[2]` matching numbered sources, and a **Sources** section at the end. Pass `response.answer` directly to a Markdown renderer.

### Multi-hop reasoning (`thinking_steps > 1`)

```python
response = await engine.ask(
    collection="agent_name",
    question="Summarise all known bugs and their root causes.",
    thinking_steps=3,     # 3 retrieval-reasoning cycles
    hops_per_step=4,      # up to 4 graph hops per cycle
    top_k=25,
    depth=3,
)
```

At each step the LLM decides what to search next. Higher `thinking_steps` = deeper answers at the cost of more LLM calls.

---

## Chat (Conversational, with Session History)

### `engine.chat()` — single turn with session memory

```python
response = await engine.chat(
    collection="agent_name",
    question="Help me understand the auth flow.",
    session_id="conv_123",    # optional — enables multi-turn history
    top_k=15,
    depth=2,
    temperature=None,
    max_tokens=None,
)
# Returns: ContextResponse (same as ask())
print(response.answer)   # Markdown
```

`session_id` groups messages into a conversation. The history is passed to the LLM for context on each turn.

### `engine.recursive_chat()` — multi-hop single question

```python
response = await engine.recursive_chat(
    collection="agent_name",
    question="What are the key revenue drivers and which accounts are at risk?",
    session_id="conv_123",    # optional
    thinking_steps=2,         # autonomous retrieval cycles
    hops_per_step=4,
    threshold=0.7,            # confidence threshold to stop early
    temperature=None,
    max_tokens=None,
)
# Returns: ContextResponse
# response.reasoning_trace includes full thinking chain
```

Use when you want the engine to autonomously refine its retrieval across multiple hops before synthesising a final answer.

---

## Streaming

### `engine.stream_chat()` — stream tokens from a single-turn chat

```python
async for chunk in engine.stream_chat(
    collection="agent_name",
    question="Explain the auth flow.",
    session_id="conv_123",
    top_k=15,
    depth=2,
    temperature=None,
    max_tokens=None,
):
    if chunk.get("type") == "node_count":
        print(f"Retrieved {chunk['count']} nodes")
    elif chunk.get("type") == "answer":
        print(chunk["content"], end="", flush=True)
```

**Chunk format:** each chunk is a `dict`:

| `type` | `content` / extra fields | When emitted |
|---|---|---|
| `"node_count"` | `count: int` | Once, before first token |
| `"answer"` | `content: str` — token(s) | Repeatedly as the LLM generates |

The stream ends when the async iterator is exhausted (no sentinel needed from the caller side).

### `engine.stream_recursive_chat()` — stream tokens from multi-hop reasoning

```python
async for chunk in engine.stream_recursive_chat(
    collection="agent_name",
    question="Deep dive on the storage architecture.",
    session_id=None,
    thinking_steps=2,
    hops_per_step=4,
    temperature=None,
    max_tokens=None,
):
    if chunk.get("type") == "thinking":
        print(f"[thinking] {chunk['content']}")
    elif chunk.get("type") == "answer":
        print(chunk["content"], end="", flush=True)
```

Additional chunk type for recursive streaming:

| `type` | Meaning |
|---|---|
| `"thinking"` | Narration emitted before each hop |
| `"node_count"` | Nodes retrieved in this hop |
| `"answer"` | Final answer token |

---

## Memory Tiers

| Tier | Purpose | Example |
|---|---|---|
| `episodic` | Specific events, recent interactions | "User clicked dark mode at 15:30Z" |
| `semantic` | Stable facts, learned preferences | "User prefers dark mode" |
| `procedural` | How-to steps, workflows | "Reset password: click forgot → check email → follow link" |
| `working` | Auto-promoted hot facts (managed by the agent) | Summary nodes created during consolidation |

---

## Node Types

| Type | Use for |
|---|---|
| `fact` | Static assertions — "The office is on 5th Street" |
| `experience` | Events with timestamp — "User visited at 15:30Z" |
| `goal` | Objectives — "User wants fewer notifications" |
| `rule` | Conditional logic — "If offline, queue messages" |
| `pattern` | Recurring behaviours — "User logs in at 9am daily" |

---

## Graph Operations

```python
# Add an explicit edge between two nodes
await engine.add_relation(
    collection="agent_name",
    from_node="node_uuid_a",
    to_node="node_uuid_b",
    relation_type="supports",   # influences | contradicts | supports | related_to | caused_by
    metadata={"strength": 0.8},
)

# Graph statistics
stats = await engine.get_graph_stats(collection="agent_name")
# {"node_count": 312, "edge_count": 87, ...}

# Collection statistics (tier breakdown)
stats = await engine.get_collection_stats(collection="agent_name")

# Remove duplicate nodes
result = await engine.dedupe_collection(collection="agent_name", dry_run=False)
```

---

## Collection Management

```python
# Collections are created lazily on first store/ask
await engine.store("new_collection", content="First memory.")

# List all collections
collections = engine.list_collections()                  # sync
collections = await engine.list_collections_async()      # async

# Unload from memory (data persists on disk)
await engine.drop_collection(collection="agent_name")

# Permanently delete all data (irreversible)
result = await engine.delete_collection(collection="agent_name")
# {"deleted_nodes": N, "deleted_clusters": N}
```

---

## Background Agent

```python
# Manually trigger a maintenance cycle (consolidation, decay, pruning)
result = await engine.trigger_agent_cycle(collection="agent_name")
# {"cycle_number": N, "nodes_processed": N, ...}

# Check agent state
status = await engine.get_agent_status(collection="agent_name")
# {"state": "idle" | "processing", "last_cycle_timestamp": "..."}
```

**What a cycle does:**
1. Merges nodes above `0.88` cosine similarity into a summary node
2. Collapses exact duplicates (highest importance wins)
3. Decays archived nodes with a 48-hour half-life
4. Prunes nodes below `0.05` importance

The cycle runs automatically in the background every 30 seconds (configurable via `STIXDB_AGENT_CYCLE_INTERVAL` on the server).

---

## Observability

```python
traces = engine.get_traces(collection="agent_name", limit=10)
for trace in traces:
    print(f"{trace['timestamp']}: {trace['message']}")
```

---

## Error Handling

```python
try:
    response = await engine.ask(collection="agent", question="...?")
except httpx.ConnectError:
    print("Server not running — start with: stixdb daemon start")
except httpx.HTTPStatusError as e:
    print(f"Server error {e.response.status_code}: {e.response.text}")
```

Common causes:

| Error | Cause | Fix |
|---|---|---|
| `ConnectError` | Server not running | `stixdb daemon start` |
| `401 Unauthorized` | Wrong or missing API key | Set `STIXDB_API_KEY` to match server |
| `404 Not Found` | Wrong collection name or URL | Check `stixdb collections list` |
| `empty answer` | `top_k` too low or question too generic | Increase `top_k`, be more specific |

---

## API Reference

| Method | Returns | Purpose |
|---|---|---|
| `engine.store(collection, content, ...)` | `dict` | Store a single memory node |
| `engine.bulk_store(collection, items)` | `dict` | Store many nodes efficiently |
| `engine.ingest_file(collection, filepath, ...)` | `dict` | Parse and chunk a file |
| `engine.ingest_folder(collection, folderpath, ...)` | `dict` | Process a directory recursively |
| `engine.retrieve(collection, query, mode="hybrid", ...)` | `list[dict]` | Raw retrieval without LLM |
| `engine.ask(collection, question, thinking_steps=1, ...)` | `ContextResponse` | LLM-synthesised Markdown answer with citations |
| `engine.chat(collection, question, session_id=None, ...)` | `ContextResponse` | Single-turn chat with session history |
| `engine.stream_chat(collection, question, ...)` | `AsyncIterator[dict]` | Stream answer tokens chunk-by-chunk |
| `engine.recursive_chat(collection, question, thinking_steps=2, ...)` | `ContextResponse` | Multi-hop autonomous reasoning |
| `engine.stream_recursive_chat(collection, question, ...)` | `AsyncIterator[dict]` | Stream multi-hop reasoning with thinking narration |
| `engine.add_relation(collection, from_node, to_node, ...)` | `dict` | Create an explicit graph edge |
| `engine.get_graph_stats(collection)` | `dict` | Node/edge counts |
| `engine.get_collection_stats(collection)` | `dict` | Tier breakdown |
| `engine.dedupe_collection(collection, dry_run)` | `dict` | Remove duplicate nodes |
| `engine.trigger_agent_cycle(collection)` | `dict` | Run consolidation/decay cycle manually |
| `engine.get_agent_status(collection)` | `dict` | Background agent state |
| `engine.drop_collection(collection)` | — | Unload from memory (data kept) |
| `engine.delete_collection(collection)` | `dict` | Permanently delete all data |
| `engine.list_collections()` | `list[str]` | All known collections (sync) |
| `engine.list_collections_async()` | `list[str]` | All known collections (async) |
| `engine.get_traces(collection, limit)` | `list[dict]` | Recent operation traces |

---

## Patterns

### Pattern 1 — Knowledge base with Q&A

```python
from stixdb import StixDBEngine

async with StixDBEngine() as engine:
    await engine.ingest_folder("kb", folderpath="./docs", tags=["official"])

    response = await engine.ask(
        "kb",
        "How do I reset my password?",
        top_k=20,
        depth=2,
    )
    print(response.answer)   # Markdown with citations
```

### Pattern 2 — Streaming chat to a UI

```python
from stixdb import StixDBEngine, StixDBConfig

config = StixDBConfig.from_env()

async def stream_to_client(collection: str, question: str):
    async with StixDBEngine(config=config) as engine:
        async for chunk in engine.stream_chat(collection, question=question):
            if chunk.get("type") == "answer":
                yield chunk["content"]   # send token to WebSocket / SSE
```

### Pattern 3 — Multi-agent shared context

```python
from stixdb import StixDBEngine

async with StixDBEngine() as engine:
    # Agent 1 stores its findings
    await engine.store("shared", content="Found bug in payment processor", tags=["bugs"], source="agent_1")

    # Agent 2 stores its findings
    await engine.store("shared", content="Root cause: timeout on retry", tags=["bugs"], source="agent_2")

    # Any agent synthesises across all findings
    response = await engine.ask("shared", "What bugs were found and what caused them?", top_k=20)
    print(response.answer)
```

### Pattern 4 — Deep reasoning with multi-hop

```python
from stixdb import StixDBEngine

async with StixDBEngine() as engine:
    response = await engine.recursive_chat(
        "proj_myapp",
        question="Summarise all architecture decisions and their consequences.",
        thinking_steps=3,
        hops_per_step=4,
    )
    print(response.answer)
    print(response.reasoning_trace)   # full thinking chain
```

### Pattern 5 — Connect to remote server

```python
from stixdb import StixDBEngine, StixDBConfig

config = StixDBConfig(
    url="https://stixdb.internal.mycompany.com",
    api_key="prod-secret-key",
    timeout=60.0,
)
async with StixDBEngine(config=config) as engine:
    response = await engine.ask("prod_agents", "What is the current deployment status?")
    print(response.answer)
```

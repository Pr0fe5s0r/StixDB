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

## Install

```bash
pip install "stixdb-engine[local-dev]"
```

---

## Get Started

**1. Configure** (run once — saves to `~/.stixdb/config.json`):
```bash
stixdb init
```

**2. Start the server:**
```bash
stixdb daemon start
```

**3. Ingest something:**
```bash
stixdb ingest ./docs/ -c my_project
```

**4. Ask a question:**
```bash
stixdb ask "What did I learn about the auth system?" -c my_project
```

That's it. StixDB is now running in the background, organizing your memories automatically.

---

## Command Reference

### Setup

| Command | Description |
|---|---|
| `stixdb init` | Configure StixDB globally (`~/.stixdb/config.json`) |
| `stixdb init --local` | Configure per-project (`.stixdb/config.json` in current directory) |
| `stixdb info` | Show the active configuration |
| `stixdb status` | Ping the running server |

```bash
stixdb init               # walk through the setup wizard
stixdb info               # show LLM, storage, port, and key settings
stixdb status             # check if the server is up
```

---

### Server

Run StixDB as a **foreground process** or a **background daemon**.

#### Foreground
```bash
stixdb serve                        # start on the configured port (default 4020)
stixdb serve --port 4321            # custom port
```

#### Daemon (background)

| Command | Description |
|---|---|
| `stixdb daemon start` | Start the server in the background |
| `stixdb daemon stop` | Stop the background server |
| `stixdb daemon restart` | Restart the background server |
| `stixdb daemon status` | Check if the daemon is running |
| `stixdb daemon logs` | View server logs |

```bash
stixdb daemon start
stixdb daemon status
stixdb daemon logs
stixdb daemon restart
stixdb daemon stop
```

---

### Ingest

Load files or entire directories into a collection.

```bash
stixdb ingest ./docs/                          # ingest a folder
stixdb ingest ./notes.md                       # ingest a single file
stixdb ingest ./src/ -c proj_myapp             # specify a collection
stixdb ingest ./data/ -c proj_myapp --tags source-code,docs
```

**Options:**

| Option | Default | Description |
|---|---|---|
| `-c`, `--collection` | from config | Target collection name |
| `--tags` | — | Comma-separated tags to attach to ingested nodes |
| `--chunk-size` | `600` | Characters per chunk |
| `--chunk-overlap` | `150` | Overlap between consecutive chunks |
| `--importance` | `0.7` | Base importance score (0.0–1.0) |

StixDB respects `.gitignore` and skips `node_modules`, `.git`, and binary files automatically.

---

### Store

Write a single memory node directly.

```bash
stixdb store "Alice is the lead engineer on the payments team." -c my_project
stixdb store "Decided to use KuzuDB for persistent storage." -c my_project --tags decisions --importance 0.9
```

**Options:**

| Option | Default | Description |
|---|---|---|
| `-c`, `--collection` | from config | Target collection |
| `--tags` | — | Comma-separated tags |
| `--importance` | `0.7` | Importance score (0.0–1.0) |
| `--node-type` | `fact` | Node type (`fact`, `summary`, etc.) |

---

### Search

Search a collection. Defaults to **hybrid mode** — keyword scoring combined with vector similarity — for the best recall without extra flags.

```bash
stixdb search "auth middleware"                              # hybrid search (default)
stixdb search "database decisions" -c proj_myapp             # search a named collection
stixdb search "in progress" -c proj_myapp --top-k 10
stixdb search "deploy steps" --mode keyword                  # fast tag/term match, no API call
stixdb search "latency bottleneck" --mode semantic           # pure vector similarity
```

**Options:**

| Option | Default | Description |
|---|---|---|
| `-c`, `--collection` | from config | Collection to search |
| `--top-k` | `5` | Number of results to return |
| `--depth` | `1` | Graph expansion depth (higher = more context) |
| `--threshold` | `0.1` | Minimum combined score (0.0–1.0) |
| `--mode` | `hybrid` | `hybrid` (keyword + semantic), `keyword` (no API, ~5ms), `semantic` (vector only) |

**Retrieval modes:**

| Mode | How it works | When to use |
|---|---|---|
| `hybrid` *(default)* | Keyword scoring (tag + content) + vector similarity, merged `0.7×semantic + 0.3×keyword` | Best general recall |
| `keyword` | Tag overlap (2× weight) + content term match. No embedding API call. ~5ms | Fast exact-term lookups |
| `semantic` | Vector embedding + cosine similarity | Paraphrase queries, conceptual matches |

---

### Ask

Ask a natural-language question. The agent retrieves relevant memory using hybrid search, reasons over it with an LLM, and returns a **Perplexity-style answer** — structured Markdown with inline citations `[1]`, `[2]` and a **Sources** section.

```bash
stixdb ask "What was I working on last session?"
stixdb ask "What decisions have been made about storage?" -c proj_myapp
stixdb ask "Summarize all known bugs" -c proj_myapp --top-k 20 --depth 3
stixdb ask "Explain the auth flow" --stream                 # stream tokens as they generate
stixdb ask "Deep dive on our storage layer" --thinking 3    # multi-hop reasoning
```

**Options:**

| Option | Default | Description |
|---|---|---|
| `-c`, `--collection` | from config | Collection to query |
| `--top-k` | `15` | Nodes to retrieve before reasoning |
| `--depth` | `2` | Graph traversal depth |
| `--thinking` | `1` | Reasoning steps (`1` = single-pass, `2+` = multi-hop) |
| `--hops` | `4` | Retrieval hops per thinking step |
| `--stream`, `-s` | `false` | Stream answer tokens progressively as they are generated |
| `--max-tokens` | server default | Cap LLM response length |

**When to use `ask` vs `search`:**
- Use `search` when you want specific facts back quickly (no LLM cost).
- Use `ask` when you need the answer synthesised and explained across multiple memories.

**Answer format:** `ask` returns rich Markdown — headers, bullet lists, code blocks, inline citations `[1]` `[2]`, and a **Sources** section. Use `--stream` to see tokens arrive in real time rather than waiting for the full response.

---

### Graph Viewer

Open an interactive visual graph of a collection in your browser.

```bash
stixdb graph                                    # view default collection
stixdb graph proj_myapp                         # view a named collection
stixdb graph proj_myapp --viewer-port 8080      # custom local port
stixdb graph proj_myapp --no-browser            # print URL only
```

<p align="center">
  <img src="assets/example_graph_evoled.png" alt="Example of an Evolved StixDB Graph" width="800" />
</p>

The viewer starts a local server (default port `4021`) and opens your browser. Node colour = memory tier. Node size = importance. Click any node to read its full content.

**Options:**

| Option | Default | Description |
|---|---|---|
| `--viewer-port`, `-p` | `4021` | Local port for the graph viewer |
| `--no-browser` | `false` | Print URL without opening the browser |

---

### Collections

Manage your collections.

```bash
stixdb collections list                         # list all collections
stixdb collections stats  my_project            # node/edge counts and tier breakdown
stixdb collections dedupe my_project            # remove duplicate chunks
stixdb collections dedupe my_project --dry-run  # preview duplicates without deleting
stixdb collections delete my_project            # delete a collection (irreversible)
stixdb collections delete my_project --yes      # skip confirmation prompt
```

---

## Configuration

StixDB is configured once with `stixdb init`. Settings are stored in `~/.stixdb/config.json` and read on every command.

To override settings for a single project, run `stixdb init --local` inside that directory. Local config takes priority over global.

### Environment Variables

You can also configure StixDB via environment variables or a `.env` file:

```bash
# LLM
STIXDB_LLM_PROVIDER=openai            # openai | anthropic | ollama | none
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# Storage
STIXDB_STORAGE_MODE=kuzu              # memory | kuzu | neo4j
STIXDB_KUZU_PATH=./my_db

# Server
STIXDB_API_PORT=4020
STIXDB_API_KEY=your-secret-key        # optional — enables auth on the REST API

# Background agent
STIXDB_AGENT_CYCLE_INTERVAL=30.0      # seconds between background cycles
STIXDB_AGENT_CONSOLIDATION_THRESHOLD=0.88
STIXDB_AGENT_DECAY_HALF_LIFE=48.0     # hours
STIXDB_AGENT_PRUNE_THRESHOLD=0.05
```

### Storage Backends

| Backend | Persistence | Install | Best For |
|---|---|---|---|
| **In-Memory** | Lost on restart | Included | Testing, prototypes |
| **KuzuDB** | On-disk | `pip install "stixdb-engine[local-dev]"` | Local dev, laptops |
| **Neo4j + Qdrant** | Production | Docker | High scale, multi-agent |

---

## How the Background Agent Works

Every 30 seconds (configurable), StixDB runs a background cycle on each collection:

1. **Merge** — nodes above `0.88` cosine similarity are merged into a summary node. Originals are archived, not deleted.
2. **Deduplicate** — exact content duplicates are collapsed (highest importance wins).
3. **Decay** — archived nodes decay with a 48-hour half-life. Nodes below `0.05` importance are pruned.

The cycle processes a capped batch of 64 nodes — CPU cost stays flat regardless of collection size.

---

## How the Graph Evolves

StixDB graphs are not static. They grow, cluster, and self-organise over time as the background agent continuously processes your memory collection. Here is what that progression looks like in the graph viewer:

### Stage 1 — Raw Ingestion

<p align="center">
  <img src="assets/evole_1.png" alt="Stage 1: Raw ingestion — isolated episodic nodes" width="800" />
</p>

Immediately after ingesting documents, the graph is a flat cloud of **green (episodic) fact nodes** with no connections. Every chunk lives in isolation — the agent has not yet had a chance to analyse relationships.

---

### Stage 2 — First Edges Form

<p align="center">
  <img src="assets/evole_2.png" alt="Stage 2: First edges form between similar nodes" width="800" />
</p>

After the first background cycle, the agent detects nodes with high semantic similarity and draws the **first edges**. Small connected clusters begin to appear inside the larger cloud. The rest of the graph remains isolated, waiting to be processed in future cycles.

---

### Stage 3 — Clusters & Working-Memory Hubs

<p align="center">
  <img src="assets/evole_4.png" alt="Stage 3: Clusters form with working-memory summary hubs" width="800" />
</p>

As cycles continue, related facts are merged into **orange (working-memory) summary nodes** that act as hubs. Episodic facts radiate outward in clear hub-and-spoke clusters, organised by topic. The graph now has meaningful topology — querying a hub retrieves an entire topic in one hop.

---

### Stage 4 — Semantic Consolidation

<p align="center">
  <img src="assets/evole_5.png" alt="Stage 4: Semantic long-term memory nodes emerge" width="800" />
</p>

Over longer periods, frequently accessed and consolidated working-memory nodes graduate into **blue (semantic) long-term memory** nodes. These represent durable, high-confidence knowledge. The graph is now a multi-tier structure: isolated facts at the edges, topic clusters in the middle, and stable semantic anchors at the core.

---

---

## For Developers

### REST API

The StixDB server exposes a REST API on `http://localhost:4020` (default).

#### Health

```
GET /health
```
```json
{ "status": "ok", "collections": ["proj_myapp", "proj_other"] }
```

---

#### Store a node

```
POST /collections/{collection}/nodes
```
```json
{
  "content": "Alice leads the payments team.",
  "node_type": "fact",
  "importance": 0.8,
  "tags": ["team", "payments"]
}
```
```json
{ "node_id": "abc123", "collection": "proj_myapp", "status": "stored" }
```

---

#### Search

```
POST /search
```
```json
{
  "query": "who leads payments",
  "collection": "proj_myapp",
  "top_k": 10,
  "threshold": 0.1,
  "depth": 1,
  "search_mode": "hybrid"
}
```

`search_mode` accepts `"hybrid"` *(default)*, `"keyword"`, or `"semantic"`.

---

#### Ask (LLM reasoning)

```
POST /collections/{collection}/ask
```
```json
{
  "question": "What decisions were made about auth?",
  "top_k": 20,
  "depth": 2,
  "thinking_steps": 1,
  "hops_per_step": 4,
  "max_tokens": 1024
}
```
```json
{
  "answer": "## Auth Decisions\n\nThe team decided to use bcrypt [1]...\n\n**Sources**\n[1] auth-decisions — ...",
  "sources": [...],
  "confidence": 0.91
}
```

The `answer` field is Markdown with inline citations `[1]`, `[2]` and a **Sources** section.

---

#### Ask — streaming

```
POST /collections/{collection}/ask/stream
```

Same request body as `/ask`. Returns a **Server-Sent Events** stream:

```
data: {"type": "answer", "content": "## Auth"}
data: {"type": "answer", "content": " Decisions\n\n"}
...
data: [DONE]
```

Each `data:` line is a JSON object with `type` (`"answer"` or `"node_count"`) and `content`. The stream terminates with `data: [DONE]`.

---

#### Ingest a file

```
POST /collections/{collection}/ingest
```
```json
{
  "path": "/absolute/path/to/file.md",
  "tags": ["docs"],
  "chunk_size": 600,
  "chunk_overlap": 150
}
```

---

#### Graph data

```
GET /collections/{collection}/graph
```

Returns all nodes and edges for use in custom visualisations.

---

#### Collection stats

```
GET /collections/{collection}/stats
```
```json
{
  "total_nodes": 312,
  "total_edges": 87,
  "nodes_by_tier": { "semantic": 120, "episodic": 192 }
}
```

---

#### Authentication

If `STIXDB_API_KEY` is set, include it on every request:

```bash
curl -H "X-API-Key: your-secret-key" http://localhost:4020/health
```

---

### Python SDK

```bash
pip install stixdb-sdk
```

```python
from stixdb_sdk import StixDBClient

with StixDBClient("http://localhost:4020", api_key="optional") as client:
    # Store
    client.memory.store("my_project", content="Alice leads payments.")

    # Ingest
    client.memory.ingest_folder("my_project", folder_path="./docs")

    # Search
    results = client.query.search("my_project", query="payments lead", top_k=5)

    # Ask
    answer = client.query.ask("my_project", question="Who leads payments?")
    print(answer.answer)
```

---

### Python Engine (embedded, no server)

Use the engine directly inside your own application — no server process needed.

```python
import asyncio
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import StorageConfig, StorageMode, ReasonerConfig, LLMProvider

async def main():
    config = StixDBConfig(
        storage=StorageConfig(mode=StorageMode.KUZU, kuzu_path="./my_db"),
        reasoner=ReasonerConfig(provider=LLMProvider.OPENAI, model="gpt-4o"),
    )
    async with StixDBEngine(config=config) as engine:
        await engine.store("my_agent", "Alice is lead engineer on payments.")

        # Semantic retrieval (no LLM)
        results = await engine.retrieve("my_agent", "payments lead", top_k=5)

        # LLM-synthesised answer
        response = await engine.ask("my_agent", "Who leads the payments team?")
        print(response.answer)
        print(response.confidence)

asyncio.run(main())
```

**Config from environment:**
```python
config = StixDBConfig.from_env()
```

---

### OpenAI-Compatible Endpoint

StixDB exposes an OpenAI-compatible `/v1/chat/completions` endpoint so any OpenAI client can query your memory graph directly:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:4020/v1", api_key="your-stixdb-key")
response = client.chat.completions.create(
    model="stixdb",
    messages=[{"role": "user", "content": "What do you know about the payments team?"}],
)
print(response.choices[0].message.content)
```

---

## License

MIT — see [LICENSE](LICENSE).

<p align="center">
  <i>AI agents deserve better than flat files. Give yours a living memory.</i>
</p>

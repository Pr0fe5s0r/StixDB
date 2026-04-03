# StixDB Quick Start — Local Development

Build intelligent agent memory on your laptop in 5 minutes. No Docker, no external services required.

## Installation

```bash
pip install "stixdb-engine[local-dev]"
```

This installs:
- StixDB engine with KuzuDB (persistent on-disk graph)
- sentence-transformers (local embeddings)
- All dependencies

## Your First Agent Memory

```python
import asyncio
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import StorageConfig, StorageMode, ReasonerConfig, LLMProvider

async def main():
    # Configure: persistent local storage, no LLM (Search API only)
    config = StixDBConfig(
        storage=StorageConfig(
            mode=StorageMode.KUZU,
            kuzu_path="./my_agent_memory",  # data persists here
        ),
        reasoner=ReasonerConfig(provider=LLMProvider.NONE),
    )

    async with StixDBEngine(config=config) as engine:
        # Store agent memories
        await engine.store(
            "my_agent",
            "Alice is the lead engineer on the payments team",
            node_type="entity",
            tags=["team", "contacts"],
            importance=0.9,
        )

        await engine.store(
            "my_agent",
            "Project deadline is June 1st, 2026",
            node_type="fact",
            tags=["deadline", "project"],
            importance=0.85,
        )

        # Search agent memory (no LLM needed)
        results = await engine.retrieve(
            "my_agent",
            query="Who is responsible for the payments deadline?",
            top_k=5,
        )

        for result in results:
            print(f"[{result['score']:.3f}] {result['content']}")
            print(f"  Tier: {result['tier']} | Type: {result['node_type']}")

asyncio.run(main())
```

**Run it:**
```bash
python my_agent.py
```

**Close and restart your process.**
All memories persist in `./my_agent_memory/` — they're still there on the next run.

---

## Add LLM Reasoning (Sonar API)

To unlock `ask()` and `chat()` (grounded answers with citations), set an LLM key:

```python
from stixdb.config import ReasonerConfig, LLMProvider

config = StixDBConfig(
    storage=StorageConfig(
        mode=StorageMode.KUZU,
        kuzu_path="./my_agent_memory",
    ),
    reasoner=ReasonerConfig(
        provider=LLMProvider.OPENAI,  # or ANTHROPIC
        model="gpt-4o",
        # OpenAI key from OPENAI_API_KEY env var
    ),
)

async with StixDBEngine(config=config) as engine:
    # Now ask() works — returns answer + citations + reasoning trace
    response = await engine.ask(
        "my_agent",
        question="Who is responsible for the payments deadline?",
    )
    print(f"Answer: {response.answer}")
    print(f"Confidence: {response.confidence}")
    for source in response.sources:
        print(f"  Source: {source.content} (score: {source.score:.3f})")
```

**Set your API key:**
```bash
export OPENAI_API_KEY=sk-...
# or
export ANTHROPIC_API_KEY=sk-ant-...
```

---

## Ingest Documents

### From a file

```python
# PDF, TXT, MD supported (native text only)
ids = await engine.ingest_file(
    "my_agent",
    filepath="./docs/roadmap.pdf",
    source_name="roadmap.pdf",
    tags=["roadmap", "planning"],
    chunk_size=1000,
    chunk_overlap=200,
)
print(f"Ingested {len(ids)} chunks")
```

### From a folder

```python
ids = await engine.ingest_folder(
    "my_agent",
    folderpath="./docs",
    recursive=True,
    tags=["documentation"],
)
```

### Bulk from dicts

```python
await engine.bulk_store(
    "my_agent",
    items=[
        {
            "content": "Sprint 1 complete",
            "node_type": "event",
            "tags": ["sprint"],
        },
        {
            "content": "Sprint 2 in progress",
            "node_type": "event",
            "tags": ["sprint"],
        },
    ],
)
```

### From LangChain Documents

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

# Load from anywhere (WebBaseLoader, PyPDFLoader, etc.)
raw_docs = [
    Document(
        page_content="Transformers use multi-head self-attention...",
        metadata={"source": "arxiv", "date": "2017"},
    )
]

# Split
splitter = RecursiveCharacterTextSplitter(chunk_size=200, chunk_overlap=30)
chunks = splitter.split_documents(raw_docs)

# Ingest
ids = await engine.ingest_file(
    "my_agent",
    filepath=chunks,  # pass the list directly
    source_name="transformers_paper",
)
```

---

## Full Example: Multi-Turn Agent Chat

```python
import asyncio
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import StorageConfig, StorageMode, ReasonerConfig, LLMProvider

async def main():
    config = StixDBConfig(
        storage=StorageConfig(mode=StorageMode.KUZU, kuzu_path="./agent_memory"),
        reasoner=ReasonerConfig(provider=LLMProvider.OPENAI, model="gpt-4o"),
    )

    async with StixDBEngine(config=config) as engine:
        # Ingest some context
        await engine.store(
            "assistant",
            "I'm an AI assistant helping with project management",
            node_type="fact",
            tags=["identity"],
        )
        await engine.store(
            "assistant",
            "The team is working on a web platform launch in Q3 2026",
            node_type="fact",
            tags=["project", "timeline"],
        )

        # Multi-turn conversation
        session_id = "user_123"

        # Turn 1
        response = await engine.chat(
            "assistant",
            message="What are we building?",
            session_id=session_id,
        )
        print(f"Q: What are we building?\nA: {response.answer}\n")

        # Turn 2 (conversation context is preserved via agent memory)
        response = await engine.chat(
            "assistant",
            message="When's the deadline?",
            session_id=session_id,
        )
        print(f"Q: When's the deadline?\nA: {response.answer}\n")

asyncio.run(main())
```

---

## Configuration

### Environment Variables

Create a `.env` file or export variables:

```bash
# Storage
STIXDB_STORAGE_MODE=kuzu
STIXDB_KUZU_PATH=./my_agent_memory

# LLM (optional)
STIXDB_LLM_PROVIDER=openai
STIXDB_LLM_MODEL=gpt-4o
OPENAI_API_KEY=sk-...

# Embedding (default: sentence-transformers)
STIXDB_EMBEDDING_PROVIDER=sentence_transformers
STIXDB_EMBEDDING_MODEL=all-MiniLM-L6-v2

# Agent tuning
STIXDB_AGENT_CYCLE_INTERVAL=30.0              # seconds
STIXDB_AGENT_CONSOLIDATION_THRESHOLD=0.88     # merge threshold
STIXDB_AGENT_DECAY_HALF_LIFE=48.0             # hours
STIXDB_AGENT_PRUNE_THRESHOLD=0.05             # importance floor

# Observability
STIXDB_LOG_LEVEL=INFO
STIXDB_ENABLE_TRACES=true
```

Then load in code:

```python
config = StixDBConfig.from_env()
```

### Programmatic Config

```python
from stixdb.config import (
    StixDBConfig, StorageConfig, StorageMode,
    ReasonerConfig, LLMProvider,
    AgentConfig, EmbeddingConfig,
)

config = StixDBConfig(
    storage=StorageConfig(
        mode=StorageMode.KUZU,
        kuzu_path="./agent_data",
    ),
    reasoner=ReasonerConfig(
        provider=LLMProvider.OPENAI,
        model="gpt-4o",
        temperature=0.2,
        max_tokens=2048,
        max_context_nodes=20,
    ),
    agent=AgentConfig(
        cycle_interval_seconds=30.0,
        consolidation_similarity_threshold=0.88,
        decay_half_life_hours=48.0,
        prune_importance_threshold=0.05,
        working_memory_max_nodes=256,
        lineage_safe_mode=True,
    ),
    embedding=EmbeddingConfig(
        provider=EmbeddingProvider.SENTENCE_TRANSFORMERS,
        model="all-MiniLM-L6-v2",
    ),
)

async with StixDBEngine(config=config) as engine:
    # ... your code
```

---

## How the Background Agent Works

Every 30 seconds (configurable), the agent runs a perceive → plan → act cycle:

### PERCEIVE
Track which nodes are accessed in queries.

### PLAN
Score "heat" of each node based on:
- **Frequency**: how many times accessed in last 24h (saturates at 10)
- **Recency**: how recently accessed (half-life 12h)

Heat = 0.6 × frequency + 0.4 × recency

### ACT
1. **Promote hot nodes** (heat > 0.65) → "working memory" tier (+0.15 boost)
2. **Demote cold nodes** (decay < 0.08) → "archived" tier
3. **Merge duplicates** (cosine similarity > 0.88) → new summary node
4. **Prune cold stuff** (importance < 0.05 and archived) → delete permanently

This self-organizing behavior means:
- Hot information rises to the top automatically
- Stale facts fade away over time
- Duplicates merge into summaries
- Your agent's memory stays relevant and compact

---

## Memory Tiers

```
working     ← hot, frequently accessed (+0.15 retrieval boost)
episodic    ← recent, not yet generalised
semantic    ← generalised knowledge (often from consolidation)
procedural  ← skills and how-to sequences
archived    ← cold, eligible for pruning
```

The agent automatically moves nodes between tiers based on access patterns.

---

## Inspection & Debugging

### Graph stats

```python
stats = await engine.get_collection_stats("my_agent")
print(stats)
# {
#   "total_nodes": 42,
#   "total_edges": 15,
#   "nodes_by_tier": {"working": 12, "episodic": 15, "semantic": 10, "archived": 5},
#   "nodes_by_type": {"fact": 25, "entity": 10, "event": 7},
# }
```

### Agent status

```python
status = await engine.get_agent_status("my_agent")
print(status)
# {
#   "collection": "my_agent",
#   "cycles_completed": 42,
#   "last_cycle_duration_ms": 345,
#   "next_cycle_at": "2026-04-03T10:45:00Z",
# }
```

### Trigger a cycle manually

```python
await engine.trigger_agent_cycle("my_agent")
```

### Traces (reasoning & consolidation)

```python
traces = await engine.get_traces(collection="my_agent", limit=10)
for trace in traces:
    print(f"{trace.timestamp} | {trace.type} | {trace.details}")
```

---

## Persistence & Restart

Data is stored in the `kuzu_path` directory (default: `./my_agent_memory/`).

**Backing up:**
```bash
cp -r ./my_agent_memory ./my_agent_memory.backup
```

**Resetting:**
```bash
rm -rf ./my_agent_memory
```

On the next run, a fresh database is created.

---

## Next Steps

- **Add more features:** See the [Cookbooks](cookbooks/) for advanced patterns
- **Scale up:** Move to Docker+Neo4j in [PRODUCTION.md](PRODUCTION.md)
- **Integrate:** Use the REST API or Python SDK
- **Customize:** Tune agent parameters in config

---

## Troubleshooting

**"kuzu package not installed"**
```bash
pip install kuzu>=0.6
```

**"Cannot open database at path XYZ"**
The directory must be writable. Check permissions:
```bash
ls -la ./my_agent_memory/
```

**"API key not found"**
```bash
export OPENAI_API_KEY=sk-...
# or set it in .env
```

**Memories not persisting across restarts**
Verify you're using `StorageMode.KUZU`, not `StorageMode.MEMORY`.

**Agent not consolidating**
Check agent status and traces:
```python
status = await engine.get_agent_status("my_agent")
print(f"Cycles: {status['cycles_completed']}")
```

---

## Resources

- [Main README](README.md) — Project overview
- [PRODUCTION.md](PRODUCTION.md) — Docker deployment
- [Cookbooks](cookbooks/) — Advanced examples
- [Architecture Docs](doc/) — Deep dives


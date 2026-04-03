---
name: engine-memory-layer
description: Use this skill whenever the user asks about using StixDBEngine directly for memory management, agentic context, reasoning, chat, or advanced memory operations. This includes storing memories, asking questions, retrieving context, managing collections, ingesting files, streaming chat, recursive reasoning, maintaining memory graphs, managing agent cycles, multi-agent coordination, and any workflow using engine.store(), engine.ask(), engine.chat(), engine.stream_chat(), engine.ingest_file(), etc. Whether they mention the engine, StixDB directly, or agentic memory workflows, this skill provides comprehensive guidance on all engine-level operations.
compatibility: Requires stixdb Python package, Python 3.8+, async/await support
---

# StixDB Engine Memory Layer Skill

Use this skill to work with the StixDBEngine for comprehensive agentic context management. The engine provides high-level memory operations, multi-agent coordination, streaming chat, and intelligent reasoning over your memory graph.

## Quick Start

### Initialization
```python
from stixdb import StixDBEngine, StixDBConfig

# Defaults: in-memory, no LLM
engine = StixDBEngine()
await engine.start()

# With configuration
config = StixDBConfig.from_env()  # Reads from environment
engine = StixDBEngine(config)
await engine.start()
```

### Basic Workflow
```python
# Store a memory
await engine.store(
    collection="my_agent",
    content="User prefers dark mode",
    node_type="fact",
    tier="semantic",
    tags=["ui", "preferences"]
)

# Ask a question (with reasoning)
response = await engine.ask(
    collection="my_agent",
    question="What are the user's preferences?",
    top_k=15
)
print(response.answer)

# Chat (conversational with memory)
chat_response = await engine.chat(
    collection="my_agent",
    message="How should I personalize the UI?",
    conversation_id="conv_123"
)
print(chat_response.text)

await engine.stop()
```

### Context Manager
```python
async with StixDBEngine() as engine:
    await engine.start()
    result = await engine.ask(...)
    # Automatically stops when exiting
```

---

## Lifecycle Management

### Start Engine
Initialize the engine before any operations:
```python
engine = StixDBEngine()
await engine.start()
# Initializes storage, vector store, embedding client, observability
# Collections are lazily created as needed
```

**What happens on start:**
- Configures logging and structured observability
- Initializes storage backend (in-memory, KuzuDB, or Neo4j)
- Builds vector store for semantic search
- Starts metrics collection if enabled
- Loads existing collections from persistent storage

### Stop Engine
Gracefully shut down when done:
```python
await engine.stop()
# Stops all collection agents
# Closes all connections (storage, vector store)
# Finalizes metrics
```

### Collection Listing
```python
# Synchronous
collections = engine.list_collections()

# Asynchronous
collections = await engine.list_collections_async()
```

---

## Memory Tiers (Temporal Organization)

The engine organizes memories into four tiers:

### `episodic`
- Individual experiences and specific events
- "User clicked button X at 3pm on March 5th"
- Used for: Recent interactions, one-time events, conversations
- Example:
  ```python
  await engine.store(
      collection="user_agent",
      content="User completed checkout at 2025-03-15T15:30Z",
      tier="episodic"
  )
  ```

### `semantic`
- General knowledge and extracted facts
- "User prefers dark mode"
- Used for: Learned patterns, user preferences, domain facts
- Example:
  ```python
  await engine.store(
      collection="user_agent",
      content="User prefers dark mode and minimalist design",
      tier="semantic",
      importance=0.9  # Highlight important preferences
  )
  ```

### `procedural`
- How to do things; processes and workflows
- "To access settings: Menu → Settings → Preferences"
- Used for: Step-by-step instructions, workflows, SOPs
- Example:
  ```python
  await engine.store(
      collection="help_agent",
      content="To reset password: Click forgot password → Check email → Follow link → Create new password",
      tier="procedural"
  )
  ```

### `summary`
- High-level consolidated summaries (auto-maintained)
- "User consistently prefers accessibility-focused settings"
- Created by: Automatic maintenance cycles
- Read-only during normal operations; system manages during maintenance

---

## Node Types (What Memories Represent)

Categorize memories by their semantic type:

| Type | Use For | Example |
|------|---------|---------|
| `fact` | Static assertions and knowledge | "The office is on 5th Street" |
| `experience` | Specific events and moments | "User visited today at 3pm" |
| `goal` | Objectives and intentions | "User wants to reduce notifications" |
| `rule` | Conditional logic | "If offline, queue messages" |
| `pattern` | Recurring behaviors | "User logs in every morning at 9am" |

Example:
```python
await engine.store(
    collection="agent",
    content="User works from 9am-5pm EST",
    node_type="pattern",
    tier="semantic",
    tags=["schedule", "user_behavior"]
)
```

---

## Storing Memories

### Single Store
```python
result = await engine.store(
    collection="agent_name",
    
    # Required
    content="The memory content (string)",
    
    # Optional: Classification
    node_type="fact",      # fact, experience, goal, rule, pattern
    tier="episodic",       # episodic, semantic, procedural, summary
    
    # Optional: Importance and lifecycle
    importance=0.5,        # 0.0 (low) to 1.0 (high)
    pinned=False,          # If True, won't be removed during cleanup
    
    # Optional: Metadata and sourcing
    source="module_name",
    source_agent_id="worker_1",
    tags=["tag1", "tag2"],
    metadata={"custom_field": "value"},
    node_id="optional_custom_id"
)
```

**Returns:**
```python
{
    "id": "uuid_...",
    "collection": "agent_name",
    "content": "...",
    "node_type": "fact",
    "tier": "episodic",
    "importance": 0.5,
    "created_at": "2025-03-15T10:30:00Z",
    "pinned": False,
    "tags": ["tag1", "tag2"],
}
```

**Best Practices:**
- Keep content atomic (one idea per memory)
- Use importance to weight critical facts (0.8+) vs. background (0.2-0.4)
- Pin important facts that shouldn't be forgotten
- Use consistent tags across related memories
- Include source/source_agent_id for audit trails in multi-agent systems

### Bulk Store
Store multiple memories efficiently:

```python
items = [
    {"content": "Fact 1", "tier": "semantic", "importance": 0.8},
    {"content": "Fact 2", "tier": "semantic", "importance": 0.7},
    {"content": "Fact 3", "tier": "episodic", "importance": 0.5},
]

result = await engine.bulk_store(
    collection="agent_name",
    items=items  # Each item follows same schema as store()
)
```

**When to use:**
- Loading batch data (initialization, bulk imports)
- Storing many related memories
- Performance-sensitive situations

---

## Ingesting Files and Folders

### Ingest Single File
Automatically parse and chunk documents:

```python
result = await engine.ingest_file(
    collection="agent_name",
    file_path="/path/to/document.pdf",
    
    # Optional
    tags=["source_doc"],
    chunk_size=1000,       # Characters per chunk
    chunk_overlap=200,     # Overlap for context
    parser="auto",         # or specific: "pdf", "markdown", etc.
    preserve_structure=True,  # Maintain formatting when possible
)
```

**Returns:**
```python
{
    "collection": "agent_name",
    "file": "document.pdf",
    "chunks_created": 42,
    "bytes_processed": 123456,
    "time_seconds": 2.3,
    "tags_applied": ["source_doc"]
}
```

**Supported file types:**
- Documents: `.pdf`, `.md`, `.txt`, `.rst`, `.html`
- Data: `.csv`, `.tsv`, `.json`, `.jsonl`, `.yaml`
- Code: `.py`, `.js`, `.ts`, `.java`, `.go`, `.rs`, `.sql`, etc.
- Config: `.toml`, `.ini`, `.cfg`, `.conf`

### Ingest Entire Folder
Recursively process all files in a directory:

```python
result = await engine.ingest_folder(
    collection="agent_name",
    folder_path="/path/to/docs",
    
    # Optional
    tags=["documentation"],
    chunk_size=1000,
    chunk_overlap=200,
    parser="auto",
    recursive=True,  # Include subdirectories
)
```

**Returns:**
```python
{
    "collection": "agent_name",
    "folder": "/path/to/docs",
    "files_processed": 45,
    "files_skipped": 3,
    "total_chunks": 312,
    "time_seconds": 8.5,
    "ingested": [
        {
            "filepath": "...",
            "relative_path": "...",
            "chunks": 12
        }
    ],
    "skipped": ["file1.exe", "file2.bin"]
}
```

**Best Practices:**
- Use `chunk_size=1000` as baseline; adjust for document density
- Set `chunk_overlap=200` to preserve cross-chunk context
- Use consistent tags to group related documents
- Use `recursive=True` for hierarchical folder structures
- Process large document sets in batches to avoid timeouts

---

## Retrieving and Querying Memories

### Retrieve Raw Memories
Get memories without LLM reasoning:

```python
result = await engine.retrieve(
    collection="agent_name",
    query="user preferences",
    
    # Optional: Tuning retrieval
    top_k=10,           # How many to return
    threshold=0.25,     # Minimum similarity (0.0-1.0)
    depth=1,            # Graph traversal depth
)
```

**Returns:**
```python
{
    "query": "user preferences",
    "matches": [
        {
            "id": "uuid",
            "content": "User prefers dark mode",
            "similarity": 0.92,
            "node_type": "fact",
            "tier": "semantic"
        },
        ...
    ],
    "count": 5
}
```

### Ask (Agentic Question Answering)
Get an LLM-reasoned answer over retrieved memories:

```python
response = await engine.ask(
    collection="agent_name",
    question="What are the user's accessibility needs?",
    
    # Optional: Tuning retrieval
    top_k=15,          # More context for reasoning
    threshold=0.25,
    depth=2,           # 2-hop traversal
    
    # Optional: LLM control
    system_prompt=None,    # Override system instructions
    output_schema=None,    # Enforce JSON schema if set
)
```

**Response object (`ContextResponse`):**
```python
response.answer           # LLM's synthesized answer (str)
response.reasoning_trace  # Step-by-step reasoning (str)
response.sources          # List of source memories used
response.follow_up_query  # Suggested next question (str)

# Access sources
for source in response.sources:
    print(f"  - {source.content} (relevance: {source.relevance})")
```

**When to use Ask:**
- You need reasoning or synthesis over multiple memories
- You want source attribution
- The question requires inference or comparison
- You're building conversational workflows

**Example:**
```python
response = await engine.ask(
    collection="customer_agent",
    question="What product should I recommend based on purchase history?",
    top_k=20,  # Get broad context
)
print(f"Recommendation: {response.answer}")
print(f"Reasoning: {response.reasoning_trace}")
```

---

## Chat and Conversation

### Single Chat Turn
Get a response in a conversation context:

```python
response = await engine.chat(
    collection="agent_name",
    message="Help me with this issue",
    
    # Optional: Conversation tracking
    conversation_id="conv_123",    # Group related messages
    
    # Optional: Tuning
    top_k=15,
    depth=2,
    system_prompt=None,
)

print(response.text)  # Chat response
```

**Returns:**
```python
{
    "text": "Here's how to...",
    "reasoning": "Based on...",
    "conversation_id": "conv_123",
    "timestamp": "2025-03-15T15:30:00Z",
    "sources": [...]  # Memories used
}
```

### Streaming Chat
Stream responses token-by-token for real-time feedback:

```python
async for chunk in await engine.stream_chat(
    collection="agent_name",
    message="Stream this response",
    conversation_id="conv_123",
):
    print(chunk, end="", flush=True)
```

**Chunks are:**
- Text tokens as they're generated
- Real-time, suitable for UI streaming
- Returns as async iterator

### Recursive Chat
Multi-turn conversation with automatic context refinement:

```python
messages = [
    "Tell me about our Q4 revenue",
    "How much came from enterprise?",
    "Which accounts are at risk?",
]

response = await engine.recursive_chat(
    collection="agent_name",
    messages=messages,
    conversation_id="conv_123",
    
    # Optional
    depth=2,
    max_turns=3,  # How many follow-ups to auto-generate
)

print(response.final_answer)
print(response.full_transcript)  # All turns
```

**Returns:**
```python
{
    "final_answer": "...",
    "full_transcript": [
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": "..."},
        ...
    ],
    "reasoning_steps": [...]
}
```

### Streaming Recursive Chat
Stream multi-turn conversations:

```python
async for chunk in await engine.stream_recursive_chat(
    collection="agent_name",
    messages=["question 1", "question 2"],
    conversation_id="conv_123",
):
    print(chunk, end="", flush=True)
```

---

## Graph Operations

### Add Relations Between Memories
Create explicit connections in the memory graph:

```python
result = await engine.add_relation(
    collection="agent_name",
    from_node="user_preference_uuid",
    to_node="ui_setting_uuid",
    relation_type="influences",  # Type of relationship
    metadata={"strength": 0.8}
)
```

**Relationship types:**
- `influences` — A affects B
- `contradicts` — A conflicts with B
- `supports` — A backs up B
- `related_to` — A is related to B
- `prerequisite_for` — A must happen before B
- `caused_by` — A was caused by B

### Get Graph Statistics
```python
stats = await engine.get_graph_stats(collection="agent_name")
print(f"Nodes: {stats['node_count']}")
print(f"Edges: {stats['edge_count']}")
print(f"Clusters: {stats['cluster_count']}")
```

### Get Collection Statistics
```python
stats = await engine.get_collection_stats(collection="agent_name")
print(stats)
# Returns detailed breakdown by tier, node_type, etc.
```

---

## Collection Management

### Create/Access Collection
Collections are lazily created on first access:
```python
# Automatically created on first store/ask
await engine.store(
    collection="new_agent",
    content="First memory",
)
# Collection now exists and persists
```

### Drop Collection
Remove a collection from memory (keeps data in storage):
```python
await engine.drop_collection(collection="agent_name")
# Collection unloaded but data persists
```

### Delete Collection
Permanently delete all data for a collection:
```python
result = await engine.delete_collection(collection="agent_name")
print(f"Deleted {result['deleted_nodes']} nodes")
print(f"Deleted {result['deleted_clusters']} clusters")
```

**Warning:** This permanently removes all data for the collection.

---

## Agent Cycles and Maintenance

### Trigger Agent Cycle
Run the autonomous agent for a collection:

```python
result = await engine.trigger_agent_cycle(collection="agent_name")
print(f"Executed cycle {result['cycle_number']}")
print(f"Processed {result['nodes_processed']} nodes")
```

**What happens during a cycle:**
- Agent reasons over memories
- Creates new relations and insights
- Consolidates episodic memories into semantic tier
- Updates importance weights
- Maintains summary layer

### Get Agent Status
Check what the agent is doing:

```python
status = await engine.get_agent_status(collection="agent_name")
print(f"Status: {status['state']}")  # idle, processing, etc.
print(f"Last cycle: {status['last_cycle_timestamp']}")
```

### Get Traces
Access observability traces for debugging:

```python
traces = engine.get_traces(
    collection="agent_name",
    limit=10,
    filter_by_level="INFO"
)
for trace in traces:
    print(f"{trace.timestamp}: {trace.message}")
```

---

## Configuration

### Default Configuration
```python
from stixdb import StixDBConfig

config = StixDBConfig.from_env()  # Reads environment variables
engine = StixDBEngine(config)
```

### Custom Configuration
```python
from stixdb import StixDBConfig, StorageMode, VectorBackend, LLMProvider

config = StixDBConfig(
    storage=StorageConfig(
        mode=StorageMode.KUZU,       # In-memory, KuzuDB, or Neo4j
        kuzu_path="./stix_data",
    ),
    embedding=EmbeddingConfig(
        provider="openai",            # Provider for embeddings
        api_key="sk-...",
    ),
    reasoner=ReasonerConfig(
        provider=LLMProvider.ANTHROPIC,  # LLM for reasoning
        model="claude-opus",
    ),
    storage_backend=StorageMode.KUZU,
    vector_backend=VectorBackend.CHROMA,
    log_level="INFO",
    verbose=True,
)

engine = StixDBEngine(config)
```

### Environment Variables
```bash
# Storage
STIX_STORAGE_MODE=kuzu
STIX_KUZU_PATH=./stix_data

# Embeddings
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=sk-...

# LLM Reasoning
REASONER_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-...

# Observability
STIX_LOG_LEVEL=INFO
STIX_ENABLE_METRICS=true
STIX_METRICS_PORT=8000
```

---

## Best Practices

### Memory Organization Pattern
```python
# 1. Store specific event (episodic)
await engine.store(
    collection="agent",
    content="User clicked dark mode button at 2025-03-15T15:30Z",
    node_type="experience",
    tier="episodic",
    tags=["ui", "interaction"]
)

# 2. Extract general fact (semantic)
await engine.store(
    collection="agent",
    content="User prefers dark mode",
    node_type="fact",
    tier="semantic",
    importance=0.9,
    pinned=True,
    tags=["ui", "preference"]
)

# 3. Query for synthesis
response = await engine.ask(
    collection="agent",
    question="What are user's UI preferences?",
)
# Answer draws from both episodic and semantic tiers
```

### Collection Design
- One collection per agent/entity
- Use collections for isolation (performance and organization)
- Name consistently: `user_123`, `agent_support`, `bot_task_manager`

### Importance Strategy
- Pin facts you can't afford to lose
- Use importance 0.8+ for critical preferences
- Use 0.5-0.7 for normal facts
- Use 0.2-0.4 for background/historical

### Tuning for Performance
- Increase `chunk_size` for large documents (1500-2000)
- Decrease for technical docs (500-800)
- Set `depth=1` for speed, `depth=2` for comprehensiveness
- Use `threshold=0.5` for precise matches, `0.15` for broad

### Multi-Agent Coordination
```python
# Agent 1 stores
await engine.store(
    collection="agent_1",
    content="Found problem X",
    source="agent_1",
)

# Agent 2 retrieves from shared collection
response = await engine.ask(
    collection="shared_context",
    question="What problems were found?",
)

# Use source_agent_id to track origin
for source in response.sources:
    print(f"From: {source.source_agent_id}")
```

---

## Streaming Best Practices

### Stream vs Non-Stream Tradeoff
```python
# Non-streaming (wait for complete answer)
response = await engine.ask(...)
print(response.answer)

# Streaming (show progress to user)
async for chunk in await engine.stream_chat(...):
    print(chunk, end="", flush=True)
```

### Handling Stream Errors
```python
try:
    async for chunk in await engine.stream_chat(...):
        print(chunk, end="", flush=True)
except Exception as e:
    print(f"Stream interrupted: {e}")
```

---

## Error Handling

```python
from stixdb.context.response import ContextError

try:
    result = await engine.ask(collection="agent", question="...?")
except ContextError as e:
    print(f"Context error: {e.message}")
except Exception as e:
    print(f"Unexpected error: {e}")
finally:
    await engine.stop()
```

Common errors:
- **Collection not found**: Created lazily; check collection name
- **Engine not started**: Call `await engine.start()` first
- **Storage connection**: Check persistence backend is running
- **LLM error**: Verify API keys and model availability

---

## API Reference Quick Summary

| Operation | Method | Purpose |
|-----------|--------|---------|
| Store memory | `engine.store()` | Single memory, full control |
| Bulk store | `engine.bulk_store()` | Multiple memories efficiently |
| Ingest file | `engine.ingest_file()` | Parse and chunk a document |
| Ingest folder | `engine.ingest_folder()` | Process directory recursively |
| Retrieve | `engine.retrieve()` | Get raw memories matching query |
| Ask | `engine.ask()` | Agentic Q&A with reasoning |
| Chat | `engine.chat()` | Single-turn conversation |
| Stream chat | `engine.stream_chat()` | Stream chat response tokens |
| Recursive chat | `engine.recursive_chat()` | Multi-turn conversation |
| Stream recursive | `engine.stream_recursive_chat()` | Stream multi-turn conversation |
| Add relation | `engine.add_relation()` | Create graph connection |
| Get stats | `engine.get_graph_stats()` | Graph statistics |
| Agent cycle | `engine.trigger_agent_cycle()` | Run autonomous reasoning |
| Agent status | `engine.get_agent_status()` | Check agent state |
| Drop collection | `engine.drop_collection()` | Unload from memory |
| Delete collection | `engine.delete_collection()` | Permanently delete data |

---

## Advanced Patterns

### Pattern 1: Knowledge Base with Automatic Maintenance
```python
# Load documentation
await engine.ingest_folder(
    collection="knowledge_base",
    folder_path="./docs",
    tags=["official"]
)

# Periodically trigger reasoning
async def maintain_knowledge():
    while True:
        await engine.trigger_agent_cycle("knowledge_base")
        await asyncio.sleep(3600)  # Every hour

# Query for support
response = await engine.ask(
    collection="knowledge_base",
    question="How do I reset my password?"
)
```

### Pattern 2: User Preferences Evolution
```python
# Store interaction
await engine.store(
    collection="user_agent",
    content="User spent 2 hours in dark mode, then switched to light",
    node_type="experience",
    tier="episodic"
)

# Agent extracts pattern
await engine.trigger_agent_cycle("user_agent")

# Ask about preferences
response = await engine.ask(
    collection="user_agent",
    question="What's the user's actual mode preference?"
)
# Agent will have reasoned that preference depends on time of day
```

### Pattern 3: Multi-Agent Reasoning
```python
# Agent 1 documents findings
await engine.store(
    collection="analysis_agent",
    content="Data shows Q4 growth of 15%",
    tags=["revenue", "quarterly"]
)

# Agent 2 adds context
await engine.store(
    collection="analysis_agent",
    content="Growth driven by enterprise segment",
    tags=["revenue", "segment"]
)

# Both agents reason together
response = await engine.ask(
    collection="analysis_agent",
    question="What are the key revenue drivers?",
    top_k=20,
    depth=2
)
# Synthesizes both agents' findings
```

---
name: sdk-memory-layer
description: Use this skill whenever the user asks about storing, retrieving, searching, or querying memories using the StixDB SDK client (stixdb_sdk). This includes operations like creating collections, storing facts and experiences, ingesting documents, searching memory, asking agentic questions, using memory tiers, tags, node types, metadata, and any workflow involving the SDK's MemoryAPI, SearchAPI, or QueryAPI. Whether they mention the SDK, Python code, or client operations, this skill provides comprehensive guidance on memory management through the SDK.
compatibility: Requires stixdb-sdk Python package, Python 3.8+
---

# StixDB SDK Memory Layer Skill

Use this skill to work with the StixDB memory layer through the Python SDK client. This covers all memory operations: storing, retrieving, searching, and querying memories in collections.

## Quick Start

### Installation
```python
from stixdb_sdk import StixDBClient, AsyncStixDBClient
```

### Basic Flow
```python
# Create client (defaults to localhost:4020)
client = StixDBClient(base_url="http://localhost:4020", api_key="optional-key")

# Store a memory
result = client.memory.store(
    collection="my_agent",
    content="User prefers dark mode",
    node_type="fact",
    tags=["ui", "preferences"],
    importance=0.8
)

# Search for memories
results = client.search.create(
    query="What UI preferences does user have?",
    collection="my_agent",
    max_results=10
)

# Ask agentic question (uses reasoning)
answer = client.query.ask(
    collection="my_agent",
    question="What are the user's UI preferences?",
    top_k=15
)

client.close()
```

For async operations, use `AsyncStixDBClient` with `await` and async context managers.

---

## Memory Tiers (Temporal Organization)

Memories are organized into tiers based on how often they're accessed and their temporal scope:

### `episodic` (Default)
- Individual experiences and events
- Recent, specific memories
- Example: "User clicked the dark mode button on March 3rd"
- **When to use**: Recording specific user actions, isolated events, one-time interactions

### `semantic`
- General knowledge and facts extracted from experiences
- Domain knowledge, learned patterns
- Example: "User prefers dark mode"
- **When to use**: Storing generalizations, rules, facts that apply broadly

### `procedural`
- How to do things; actions and procedures
- Workflows, steps, best practices
- Example: "To switch theme: Settings → Appearance → Toggle Dark Mode"
- **When to use**: Storing instructions, recipes, workflows, step-by-step processes

### `summary`
- Consolidated high-level summaries
- Maintained by the system during maintenance cycles
- Example: "User has consistent UI preferences favoring accessibility"
- **When to use**: Let the system create these during maintenance; reference for overview queries

**How to specify when storing:**
```python
client.memory.store(
    collection="my_agent",
    content="...",
    tier="episodic",  # or "semantic", "procedural", "summary"
)
```

---

## Node Types (What Memories Represent)

Categorize what kind of information you're storing:

### `fact` (Default)
- Static information, assertions, knowledge
- Example: "The user's name is Alice"

### `experience`
- Events and moments in time
- Example: "User completed onboarding on March 5th"

### `goal`
- Objectives and intentions
- Example: "User wants to reduce notifications"

### `rule`
- Conditional logic and constraints
- Example: "If user is offline, queue messages for later"

### `pattern`
- Recurring behaviors and trends
- Example: "User typically logs in at 9am"

**How to specify:**
```python
client.memory.store(
    collection="my_agent",
    content="...",
    node_type="experience",  # or "fact", "goal", "rule", "pattern"
)
```

---

## Storing Memories

### Single Store
Store one memory item at a time with full control over properties:

```python
result = client.memory.store(
    collection="agent_name",
    
    # Required
    content="The actual memory content (string)",
    
    # Node classification (both optional)
    node_type="fact",  # fact, experience, goal, rule, pattern
    tier="episodic",   # episodic, semantic, procedural, summary
    
    # Importance and pinning
    importance=0.5,    # Float 0.0-1.0, defaults to 0.5
    pinned=True,       # If True, won't be removed during cleanup
    
    # Metadata and searchability
    source="agent_module",           # Where this came from
    source_agent_id="worker_1",      # Which agent created it
    tags=["category", "topic"],      # For filtering during search/query
    metadata={"custom": "value"},    # Arbitrary JSON data
    
    # Specify a node ID (optional, auto-generated if omitted)
    node_id="custom_id_123"
)
```

**Returns:**
```python
{
    "id": "node_uuid",
    "collection": "agent_name",
    "content": "...",
    "node_type": "fact",
    "tier": "episodic",
    "created_at": "2025-03-15T10:30:00Z",
    "importance": 0.5,
    ...
}
```

**Best Practices:**
- Keep content focused and atomic (one idea per memory)
- Use `importance` to highlight critical facts (0.8-1.0) vs. background knowledge (0.2-0.4)
- Use `tags` consistently for related memories (e.g., all UI preferences get `["ui"]`)
- Pin (`pinned=True`) memories that shouldn't be forgotten
- Include `source` and `source_agent_id` for multi-agent systems to track origin

### Bulk Store
Store multiple memories in one call for efficiency:

```python
items = [
    {
        "content": "First fact",
        "node_type": "fact",
        "tier": "semantic",
        "tags": ["important"],
        "importance": 0.8,
    },
    {
        "content": "Second fact",
        "node_type": "fact",
        "tier": "semantic",
        "tags": ["important"],
        "importance": 0.7,
    },
]

result = client.memory.bulk_store(
    collection="agent_name",
    items=items
)
```

**When to use bulk_store:**
- Ingesting many related memories at once
- Batch operations where network efficiency matters
- Loading initialized state (e.g., from a database export)

---

## Ingesting Documents

### Upload Single File
Automatically parse and chunk documents:

```python
result = client.memory.upload(
    collection="agent_name",
    file_path="/path/to/document.pdf",
    
    # Optional parameters
    tags=["source_document"],
    chunk_size=1000,          # Characters per chunk
    chunk_overlap=200,        # Overlap between chunks
    parser="auto",            # auto, pdf, markdown, plain_text, json
)
```

**Supported formats:**
- Plain text: `.txt`, `.md`, `.markdown`, `.rst`, `.log`
- Structured: `.csv`, `.tsv`, `.json`, `.jsonl`, `.yaml`, `.yml`, `.xml`
- Code: `.py`, `.js`, `.ts`, `.tsx`, `.jsx`, `.java`, `.c`, `.cpp`, `.cs`, `.go`, `.rs`, `.sh`, `.sql`
- Documents: `.pdf`, `.html`, `.htm`
- Config: `.toml`, `.ini`, `.cfg`, `.conf`

### Ingest Entire Folder
Recursively process all supported files in a directory:

```python
result = client.memory.ingest_folder(
    collection="agent_name",
    folder_path="/path/to/docs",
    
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
    "files_processed": 15,
    "files_skipped": 2,
    "ingested": [
        {
            "filepath": "/path/to/docs/file1.txt",
            "relative_path": "file1.txt",
            "result": {...}
        }
    ],
    "skipped": ["/path/to/docs/unsupported.bin"]
}
```

**Best Practices:**
- Use `chunk_size=1000` as default; increase for long-form documents, decrease for dense technical docs
- Set `chunk_overlap=200` to preserve context across chunks
- Use consistent `tags` to group documents by source or type
- Use `recursive=True` for folder hierarchies with nested subdirectories

---

## Retrieving Memories

### List Memories
Retrieve memories from a collection with optional filtering:

```python
result = client.memory.list(
    collection="agent_name",
    
    # Optional filters
    tier="semantic",                    # Filter by tier
    node_type="fact",                   # Filter by node type
    
    # Pagination
    limit=100,  # Max memories per page
    offset=0,   # Page offset
)
```

**Returns:**
```python
{
    "collection": "agent_name",
    "nodes": [
        {
            "id": "uuid1",
            "content": "...",
            "node_type": "fact",
            "tier": "semantic",
            "importance": 0.8,
            "created_at": "2025-03-15T10:30:00Z",
            "tags": ["ui", "preferences"],
            "pinned": True,
        },
        ...
    ],
    "count": 42,
    "total": 150
}
```

### Get Single Memory
Retrieve a specific memory by ID:

```python
memory = client.memory.get(
    collection="agent_name",
    node_id="memory_uuid"
)
```

### Delete Memory
Remove a specific memory:

```python
result = client.memory.delete(
    collection="agent_name",
    node_id="memory_uuid"
)
```

---

## Searching Memories

Search uses semantic similarity and filters to find relevant memories:

```python
results = client.search.create(
    # Query (required)
    query="What preferences does the user have?",
    # Can also pass a list of queries:
    # query=["preference 1", "preference 2"]
    
    # Collection selection
    collection="agent_name",           # Search one collection
    # OR
    collections=["agent1", "agent2"],  # Search multiple collections
    
    # Result limits
    max_results=10,       # How many final results to return
    top_k=25,             # How many candidates to consider
    threshold=0.25,       # Minimum similarity score (0.0-1.0)
    
    # Graph traversal
    depth=1,              # How far to traverse relationships
                          # depth=1: direct connections
                          # depth=2: 2 hops away
    
    # Filtering
    source_filter=["module_a"],        # Only from certain sources
    tag_filter=["ui"],                 # Only with these tags
    node_type_filter=["fact"],         # Only these node types
    tier_filter=["semantic"],          # Only these tiers
    
    # Output control
    max_chars_per_result=1200,  # Max characters in each result
    include_metadata=True,      # Include metadata in results
    include_heatmap=False,      # (Advanced) Include similarity heatmap
    sort_by="relevance",        # or "recency", "importance"
)
```

**Returns:**
```python
{
    "query": "What preferences does the user have?",
    "results": [
        {
            "id": "uuid1",
            "content": "User prefers dark mode...",
            "similarity": 0.92,
            "node_type": "fact",
            "tier": "semantic",
            "tags": ["ui", "preferences"],
            "metadata": {},
            "source": "ui_module",
        },
        ...
    ],
    "count": 3,
    "threshold": 0.25
}
```

**When to use Search:**
- Full-text semantic search with filtering
- When you want ranked results by similarity
- When you need flexible multi-collection searches
- When you want to traverse graph relationships

**Search Tips:**
- Lower `threshold` (0.15-0.25) for broad, inclusive searches
- Higher `threshold` (0.6+) for precise, exact-match searches
- Use `depth=2` for context that connects across 2 hops (slower but more thorough)
- Use `sort_by="importance"` to surface critical memories first

---

## Querying Memories (Agentic)

Query uses the LLM to reason over retrieved memories and synthesize answers:

### Ask
Get an LLM-reasoned answer to a question:

```python
result = client.query.ask(
    collection="agent_name",
    
    # Required
    question="What are the user's preferences?",
    
    # Retrieval parameters
    top_k=15,             # How many memories to retrieve
    threshold=0.25,       # Minimum similarity threshold
    depth=2,              # Graph traversal depth
    
    # LLM control
    system_prompt=None,   # Override system instructions (optional)
    output_schema=None,   # Enforce JSON schema (optional)
)
```

**Returns:**
```python
{
    "question": "What are the user's preferences?",
    "answer": "The user prefers dark mode and minimalist UI...",
    "reasoning": "Based on stored facts about UI preferences and...",
    "sources": [
        {
            "id": "uuid1",
            "content": "User prefers dark mode",
            "relevance": 0.95
        },
        ...
    ]
}
```

**When to use Ask:**
- You want intelligent synthesis of multiple memories
- The question requires reasoning or inference
- You want source attribution (what memories were used)

**Example Workflow:**
```python
# Store episodic event
client.memory.store(
    collection="user_agent",
    content="User clicked dark mode button at 3pm",
    node_type="experience",
    tier="episodic"
)

# Store semantic fact extracted later
client.memory.store(
    collection="user_agent",
    content="User prefers dark mode",
    node_type="fact",
    tier="semantic"
)

# Query gets both and reasons over them
answer = client.query.ask(
    collection="user_agent",
    question="What are user's UI preferences?"
)
# Returns: "User prefers dark mode (observed in interactions)"
```

### Retrieve
Get raw memories matching a query (no LLM reasoning):

```python
result = client.query.retrieve(
    collection="agent_name",
    query="user preferences",
    top_k=10,
    threshold=0.25,
    depth=1,
)
```

**Returns:** Simple list of matching memories (faster, no reasoning cost)

**When to use Retrieve:**
- You need raw data, not synthesized answers
- Speed is critical
- You'll do your own reasoning in code

---

## Health Check

Verify the StixDB server is running and healthy:

```python
health = client.health()
# Returns: {"status": "healthy", "timestamp": "...", ...}
```

---

## Connection Management

### Context Manager (Recommended)
```python
with StixDBClient(base_url="http://localhost:4020") as client:
    # Use client here
    result = client.memory.store(...)
# Automatically closes connection
```

### Manual Close
```python
client = StixDBClient()
try:
    result = client.memory.store(...)
finally:
    client.close()
```

### Async Context Manager
```python
async with AsyncStixDBClient() as client:
    result = await client.memory.store(...)
# Automatically closes connection
```

---

## Async Operations

All SDK operations support async for concurrent use:

```python
from stixdb_sdk import AsyncStixDBClient
import asyncio

async def main():
    async with AsyncStixDBClient() as client:
        # All methods use await
        result = await client.memory.store(
            collection="agent",
            content="...",
        )
        
        # Concurrent operations
        results = await asyncio.gather(
            client.query.ask(collection="agent", question="q1"),
            client.query.ask(collection="agent", question="q2"),
        )

asyncio.run(main())
```

---

## Best Practices

### Collection Naming
- Use lowercase with underscores: `my_agent`, `user_sessions`, `system_logs`
- One collection per agent or logical entity
- Avoid special characters

### Memory Organization
- Store **episodic** memories for specific events
- Extract and store **semantic** memories from patterns you observe
- Use **procedural** for workflows and how-to knowledge
- Let the system create **summary** tiers during maintenance

### Tagging Strategy
- Use consistent tags across related memories
- Include source, domain, and type in tags
- Example: `["ui", "dark_mode", "preference"]` instead of `["mode"]`

### Importance Weighting
- Critical facts: `0.8-1.0`
- Normal facts: `0.5-0.7`
- Background/historical: `0.2-0.4`
- System-created summaries: `0.6-0.8`

### Pinning
- Pin facts you never want forgotten
- Pin critical user preferences
- Don't over-pin (it bloats the memory)

### Search vs. Query Tradeoff
- Use **search** for fast, filtered lookups
- Use **ask** when you need reasoning or synthesis
- Use **retrieve** for raw data when speed matters

---

## Common Patterns

### Pattern 1: Update a Preference
```python
# When user changes preference, update semantic tier
client.memory.store(
    collection="user_agent",
    content="User now prefers light mode",
    node_type="fact",
    tier="semantic",
    tags=["ui", "preference"],
    importance=0.9,
    pinned=True
)

# Record the event in episodic tier
client.memory.store(
    collection="user_agent",
    content="User changed theme preference to light mode at 2025-03-15T15:30Z",
    node_type="experience",
    tier="episodic",
    tags=["ui", "event"],
)
```

### Pattern 2: Load Initial State
```python
# Bulk-load initial knowledge
facts = [
    {"content": "Company name is ACME Inc", "node_type": "fact", "tags": ["company"]},
    {"content": "CEO is John Doe", "node_type": "fact", "tags": ["leadership"]},
    {"content": "Founded in 2020", "node_type": "fact", "tags": ["history"]},
]
client.memory.bulk_store(collection="company_agent", items=facts)
```

### Pattern 3: Ingest Documentation
```python
# Load product docs into agent's memory
result = client.memory.ingest_folder(
    collection="support_agent",
    folder_path="./product_docs",
    tags=["official_documentation"],
    chunk_size=800,
    chunk_overlap=200,
)
print(f"Loaded {result['files_processed']} files")
```

### Pattern 4: Query with Context
```python
# Get answer with sources
answer = client.query.ask(
    collection="agent",
    question="What should I recommend?",
    top_k=20,  # Consider more context
    depth=2,   # Include related memories
)
print(f"Answer: {answer['answer']}")
print(f"Based on: {[s['content'] for s in answer['sources']]}")
```

---

## Error Handling

```python
try:
    result = client.memory.store(
        collection="agent",
        content="...",
    )
except Exception as e:
    print(f"Error storing memory: {e}")
```

Common errors:
- **Connection refused**: StixDB server not running
- **404 Not Found**: Collection doesn't exist (most operations create it automatically)
- **Authentication failed**: Invalid API key provided
- **Timeout**: Server is slow or unresponsive

---

## Configuration

### Custom Server
```python
client = StixDBClient(
    base_url="http://remote-server.com:4020",
    api_key="your-api-key",
    timeout=30.0  # seconds
)
```

### Environment Variables
The SDK reads from environment if not explicitly passed:
- `STIXDB_URL` — Server URL
- `STIXDB_API_KEY` — API key
- `STIXDB_TIMEOUT` — Request timeout

---

## API Reference Summary

| Method | Purpose | Key Parameters |
|--------|---------|-----------------|
| `memory.store()` | Store single memory | collection, content, tier, node_type |
| `memory.bulk_store()` | Store multiple memories | collection, items |
| `memory.list()` | List memories with filters | collection, tier, node_type, limit |
| `memory.get()` | Get specific memory | collection, node_id |
| `memory.delete()` | Delete memory | collection, node_id |
| `memory.upload()` | Ingest single file | collection, file_path, tags |
| `memory.ingest_folder()` | Ingest directory | collection, folder_path, recursive |
| `search.create()` | Semantic search | query, collection, max_results |
| `query.ask()` | Agentic question answering | collection, question, top_k |
| `query.retrieve()` | Raw retrieval | collection, query, top_k |

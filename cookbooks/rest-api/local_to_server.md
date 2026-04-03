# Transitioning from Local to Server Mode

**Quick Answer**: Same data persists. Just change how you access it.

## The Three Ways to Use StixDB

### 1. Pure Local (No Server) ✅ Simplest

```python
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import StorageConfig, StorageMode

config = StixDBConfig(
    storage=StorageConfig(mode=StorageMode.KUZU, kuzu_path="./my_memory")
)

async with StixDBEngine(config=config) as engine:
    await engine.store("agent", "Hello world")
    results = await engine.retrieve("agent", "query")
```

**Run:**
```bash
python my_agent.py
```

**When to use:**
- Writing a Python agent
- Background tasks
- Automation scripts
- No server overhead needed

---

### 2. Server Mode (HTTP API) 🌐 Most Flexible

**Step 1: Store data locally**

```python
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import StorageConfig, StorageMode

config = StixDBConfig(
    storage=StorageConfig(mode=StorageMode.KUZU, kuzu_path="./my_memory")
)

async with StixDBEngine(config=config) as engine:
    await engine.store("agent", "Some important data")
    # Data is persisted to ./my_memory/kuzu/
```

**Step 2: Start the server**

```bash
stixdb serve --port 4020
```

**Step 3: Access via HTTP (from anywhere)**

```bash
# Search
curl -X POST http://localhost:4020/collections/agent/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query": "important data", "top_k": 5}'

# Ask (with LLM)
curl -X POST http://localhost:4020/collections/agent/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What data do we have?"}'
```

**When to use:**
- Web applications
- LangChain integration
- Multiple services sharing data
- Using OpenAI SDK
- Building REST APIs

---

### 3. Server Mode + Docker 🐳 Production

**Prerequisites:**
- Docker installed
- `docker-compose.yml` in your repo

**Step 1: Start the full stack**

```bash
docker compose up -d
```

This runs:
- StixDB engine (Neo4j backend)
- Neo4j (persistent graph)
- PostgreSQL (metadata)
- MinIO (file backup)

**Step 2: Access via HTTP**

Same as above — the API is identical.

```bash
curl -X POST http://localhost:4020/collections/agent/retrieve ...
```

**When to use:**
- Production deployments
- High-traffic systems
- Multi-agent scenarios
- Persistence + scalability needed

---

## Example: Transition from Local to Server

### Initial: Local Script

```python
# store_data.py
import asyncio
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import StorageConfig, StorageMode

async def main():
    config = StixDBConfig(
        storage=StorageConfig(mode=StorageMode.KUZU, kuzu_path="./memory")
    )
    
    async with StixDBEngine(config=config) as engine:
        await engine.store("kb", "Python is cool")
        await engine.store("kb", "Async is powerful")
        
        results = await engine.retrieve("kb", "Python", top_k=2)
        print(results)

asyncio.run(main())
```

**Run:**
```bash
python store_data.py
```

**Output:**
```
[
  {'content': 'Python is cool', 'score': 0.95},
  {'content': 'Async is powerful', 'score': 0.42}
]
```

### Transition: Add Server

**Same script, but now data is available via HTTP:**

```bash
# Terminal 1: Start the server
stixdb serve --port 4020

# Terminal 2: Query via HTTP
curl -X POST http://localhost:4020/collections/kb/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query": "Python", "top_k": 2}'
```

**No changes needed to the local script.** The data is the same, just accessed differently.

---

## Use Cases & Which Mode

| Use Case | Mode | How | Server? |
|----------|------|-----|---------|
| **Agent with cron job** | Local | `async with StixDBEngine()` | ❌ No |
| **Integration test** | Local | Direct Python | ❌ No |
| **LangChain RAG** | Local or Server | `StixDBRetriever(engine)` OR HTTP | ❌/✅ Optional |
| **OpenAI SDK drop-in** | Server | `OpenAI(base_url="http://...")` | ✅ Yes |
| **Web API (Flask/FastAPI)** | Server | HTTP calls | ✅ Yes |
| **Slack bot** | Server | HTTP to StixDB | ✅ Yes |
| **Production (Docker)** | Docker Server | `docker compose up` | ✅ Yes |

---

## The Key Insight

**All three modes use the same storage backend (KUZU or NEO4J).**

- **Local**: Access data directly from your Python code
- **Server**: Access data via HTTP API (same data, different interface)
- **Docker**: Same API, but with persistent infrastructure

**Data persists across all modes.** Switch between them without data loss.

---

## Migration Path

1. **Start local** (simplest)
   ```python
   async with StixDBEngine(config) as engine:
       # Direct access
   ```

2. **Need to share data?** Start the server
   ```bash
   stixdb serve --port 4020
   ```

3. **Need scale/persistence?** Use Docker
   ```bash
   docker compose up -d
   ```

**Same data. Same code. Different access pattern.**

---

## Common Question: Do I Need Both?

**No.** Pick one:

- **Just a Python script?** → Local (no server)
- **Web app or API?** → Server (`stixdb serve`)
- **Production at scale?** → Docker (`docker compose`)

You can start with local and upgrade later without losing data.

---

## Quick Checklist

- [ ] Data stored in `./my_memory/` (or your configured path)
- [ ] Want to access via HTTP? Run `stixdb serve`
- [ ] Want production setup? Use `docker compose up -d`
- [ ] Same data works in all modes ✅

---

## See Also

- [QUICKSTART.md](../QUICKSTART.md) — Local development
- [PRODUCTION.md](../PRODUCTION.md) — Docker & scaling
- [core-sdk/03_local_vs_server.py](../core-sdk/03_local_vs_server.py) — Code examples
- [openai-compatible/with_openai_sdk.py](../openai-compatible/with_openai_sdk.py) — HTTP client usage

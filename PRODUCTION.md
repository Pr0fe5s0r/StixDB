# StixDB Production Deployment

Deploy StixDB at scale with persistent storage, multi-agent support, audit trails, and backups.

## Overview

Docker stack for production deployments:

| Service | Image | Role | Port | Data |
|---------|-------|------|------|------|
| **stixdb-engine** | `stixdb:latest` (built from Dockerfile) | REST API + agent | `4020` | ChromaDB (embedded) |
| **neo4j** | `neo4j:5.19` | Graph storage (persistent) | `7474` (browser), `7687` (bolt) | Neo4j volume |
| **postgres** | `postgres:15` | SQL metadata | `5432` | PostgreSQL volume |
| **minio** | `minio/latest` | File backup (uploaded docs) | `9000` (API), `9001` (console) | MinIO volume |

All data persists across container restarts via Docker volumes.

---

## Prerequisites

- [Docker Desktop](https://docs.docker.com/get-docker/) (or Docker Engine + Compose plugin)
- 2+ GB RAM for containers
- 5+ GB disk space for volumes
- API key for an LLM provider (OpenAI, Anthropic, Ollama, etc.)

**Verify Docker is installed:**
```bash
docker compose version
# Docker Compose version vX.Y.Z
```

---

## Setup

### 1. Clone or download the repository

```bash
git clone https://github.com/Pr0fe5s0r/StixDB.git
cd StixDB
```

### 2. Copy and configure the environment file

```bash
cp .env.example .env
```

Open `.env` and configure:

```bash
# LLM Provider (pick one)
STIXDB_LLM_PROVIDER=openai          # or: anthropic, ollama, custom, none
STIXDB_LLM_MODEL=gpt-4o
OPENAI_API_KEY=sk-...               # or ANTHROPIC_API_KEY, OLLAMA_BASE_URL, etc.

# API Security (highly recommended)
STIXDB_API_KEY=your-secret-key-here  # All API calls require X-API-Key header

# Agent tuning (optional, defaults are good for most use cases)
STIXDB_AGENT_CYCLE_INTERVAL=30.0
STIXDB_AGENT_CONSOLIDATION_THRESHOLD=0.88
STIXDB_AGENT_DECAY_HALF_LIFE=48.0
STIXDB_AGENT_PRUNE_THRESHOLD=0.05

# Observability (optional)
STIXDB_LOG_LEVEL=INFO
STIXDB_ENABLE_TRACES=true
STIXDB_ENABLE_METRICS=true

# Backup (optional)
STIXDB_BACKUP_ENABLED=true
```

**Important variables:**
- `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`: Required for Sonar API (`ask()`, `chat()`)
- `STIXDB_API_KEY`: Secures all HTTP endpoints
- Neo4j, PostgreSQL, and MinIO passwords are already configured in `docker-compose.yml`

### 3. Start the stack

**First run (builds the image, takes ~3 minutes):**
```bash
docker compose up -d
```

**Check status:**
```bash
docker compose ps
```

Expected output:
```
NAME                STATUS              PORTS
stixdb-engine       Up (healthy)        0.0.0.0:4020->4020/tcp
neo4j               Up (healthy)        0.0.0.0:7474->7474/tcp, 0.0.0.0:7687->7687/tcp
postgres            Up (healthy)        0.0.0.0:5432->5432/tcp
minio               Up                  0.0.0.0:9000->9000/tcp, 0.0.0.0:9001->9001/tcp
```

### 4. Verify the deployment

```bash
curl http://localhost:4020/health
# {"status": "ok", "storage": "neo4j", "vector": "chroma"}
```

**Optional: Open the UIs**
- **Neo4j Browser**: http://localhost:7474 (login: `neo4j` / `password`)
- **MinIO Console**: http://localhost:9001 (login: `minioadmin` / `minioadmin`)

---

## Usage

### Store a memory

```bash
curl -X POST http://localhost:4020/collections/my_agent/nodes \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Alice leads the payments team",
    "node_type": "entity",
    "tags": ["team", "contacts"],
    "importance": 0.9
  }'
```

### Search (no LLM)

```bash
curl -X POST http://localhost:4020/collections/my_agent/retrieve \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Who leads payments?",
    "top_k": 5,
    "threshold": 0.2
  }'
```

### Ask (with LLM)

```bash
curl -X POST http://localhost:4020/collections/my_agent/ask \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Who is responsible for the payments deadline?",
    "top_k": 10
  }'
```

**Response:**
```json
{
  "answer": "Alice leads the payments team and owns the Q2 deadline.",
  "confidence": 0.93,
  "sources": [
    {
      "content": "Alice leads the payments team",
      "node_type": "entity",
      "tier": "working",
      "score": 0.96
    }
  ],
  "reasoning_trace": "..."
}
```

### Upload documents

```bash
curl -X POST http://localhost:4020/collections/my_agent/upload \
  -H "X-API-Key: your-secret-key" \
  -F "file=@roadmap.pdf" \
  -F "tags=roadmap,planning"
```

---

## Python SDK

### Installation

```bash
pip install stixdb-sdk
```

### Usage

```python
from stixdb_sdk import StixDBClient

with StixDBClient(
    base_url="http://localhost:4020",
    api_key="your-secret-key"
) as client:
    # Store
    client.memory.store(
        "my_agent",
        content="Alice leads the payments team",
        tags=["team"],
        importance=0.9
    )

    # Search
    results = client.search.create(
        "payments deadline",
        collections=["my_agent"],
        max_results=5
    )

    # Ask
    response = client.query.ask(
        "my_agent",
        question="Who is responsible for payments?"
    )
    print(response["answer"])

    # Upload file
    ids = client.memory.ingest_file(
        "my_agent",
        filepath="./roadmap.pdf"
    )
```

---

## Configuration

### Storage backends

The compose stack uses:
- **Graph storage**: Neo4j (bolt://neo4j:7687)
- **Vector search**: ChromaDB (embedded, persisted to volume)
- **Metadata**: PostgreSQL (postgres:5432)
- **File backup**: MinIO (minio:9000)

### Environment variables

All StixDB config can be overridden:

```bash
# LLM
STIXDB_LLM_PROVIDER=openai
STIXDB_LLM_MODEL=gpt-4o
STIXDB_LLM_TEMPERATURE=0.2
STIXDB_LLM_MAX_TOKENS=2048
STIXDB_LLM_MAX_CONTEXT_NODES=20
STIXDB_LLM_GRAPH_TRAVERSAL_DEPTH=3

# Embedding (local by default)
STIXDB_EMBEDDING_PROVIDER=sentence_transformers
STIXDB_EMBEDDING_MODEL=all-MiniLM-L6-v2
STIXDB_EMBEDDING_DIMENSIONS=384

# Agent tuning
STIXDB_AGENT_CYCLE_INTERVAL=30.0
STIXDB_AGENT_CONSOLIDATION_THRESHOLD=0.88
STIXDB_AGENT_DECAY_HALF_LIFE=48.0
STIXDB_AGENT_PRUNE_THRESHOLD=0.05
STIXDB_AGENT_WORKING_MEMORY_MAX=256
STIXDB_AGENT_LINEAGE_SAFE_MODE=true

# Ingestion defaults
STIXDB_CHUNK_SIZE=1000
STIXDB_CHUNK_OVERLAP=200

# Observability
STIXDB_LOG_LEVEL=INFO
STIXDB_ENABLE_TRACES=true
STIXDB_ENABLE_METRICS=true
STIXDB_METRICS_PORT=9090

# API
STIXDB_API_PORT=4020
STIXDB_API_KEY=your-key

# Storage (internal Docker networking)
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
STIXDB_SQL_URL=postgresql://stixdb:stixdb_pass@postgres:5432/stixdb
```

See [`.env.example`](.env.example) for the full list.

---

## Data Persistence

### Volumes

Docker volumes store all persistent data:

```bash
docker volume ls
# DRIVER              VOLUME NAME
# local               stixdb_neo4j_data
# local               stixdb_pg_data
# local               stixdb_minio_data
# local               stixdb_stixdb_data
```

Data survives:
- Container restarts: `docker compose restart`
- Image rebuilds: `docker compose up --build`

Data is **deleted** only by:
```bash
docker compose down -v   # -v removes volumes
```

### Backup

**Backup Neo4j:**
```bash
docker exec neo4j \
  neo4j-admin database dump neo4j \
  --to-path=/data/dumps/
```

**Backup PostgreSQL:**
```bash
docker exec postgres \
  pg_dump -U stixdb stixdb \
  > stixdb_backup.sql
```

**Backup MinIO (uploaded files):**
```bash
docker exec minio \
  mc cp -r minio/stixdb-ingestion \
  ./backups/
```

---

## Monitoring & Logs

### View logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f stixdb-engine
docker compose logs -f neo4j

# Last 100 lines
docker compose logs --tail 100 stixdb-engine
```

### Prometheus metrics

If `STIXDB_ENABLE_METRICS=true`, metrics are available at:
```bash
curl http://localhost:9090/metrics
```

### Traces (reasoning & agent decisions)

```bash
curl -H "X-API-Key: your-secret-key" \
  http://localhost:4020/traces?collection=my_agent&limit=10
```

---

## Scaling

### Increase PostgreSQL connections

```bash
# In docker-compose.yml, add to postgres service:
environment:
  - max_connections=200
```

### Increase Neo4j memory

```bash
# In docker-compose.yml, add to neo4j service:
environment:
  - NEO4J_server_memory_heap_initial__size=2G
  - NEO4J_server_memory_heap_max__size=4G
```

### Run multiple agent collections

Each collection gets its own background agent. Just store data in different collections:

```bash
# Create collection 1
curl -X POST http://localhost:4020/collections/agent-1/nodes ...

# Create collection 2
curl -X POST http://localhost:4020/collections/agent-2/nodes ...

# Each runs its own agent cycle every 30s
curl http://localhost:4020/collections/agent-1/agent/status
curl http://localhost:4020/collections/agent-2/agent/status
```

---

## Maintenance

### Stop the stack

```bash
docker compose down
```

Data persists in volumes.

### Restart services

```bash
docker compose restart stixdb-engine
docker compose restart neo4j
```

### Update the image

```bash
docker compose up -d --build
```

Rebuilds from Dockerfile, preserves all data in volumes.

### Full reset (delete all data)

```bash
docker compose down -v
```

This deletes containers and volumes. Next `docker compose up -d` starts fresh.

---

## Troubleshooting

### "Connection refused" on initial startup

Neo4j, PostgreSQL, and MinIO need time to initialize. Wait 30 seconds and retry:
```bash
sleep 30
curl http://localhost:4020/health
```

### "X-API-Key header required but missing"

All requests must include the key:
```bash
curl -H "X-API-Key: your-secret-key" http://localhost:4020/health
```

### "Neo4j driver not installed"

This shouldn't happen with the provided Dockerfile. Rebuild:
```bash
docker compose up -d --build
```

### Out of memory

Increase Docker's available memory in Docker Desktop settings, or scale down agent parameters:

```bash
STIXDB_AGENT_WORKING_MEMORY_MAX=128
STIXDB_AGENT_MAX_CONSOLIDATION_BATCH=32
```

### Neo4j browser not accessible

Verify ports:
```bash
docker compose ps
# Check that neo4j has 7474 mapped
```

Try:
```bash
curl http://localhost:7474
```

### MinIO credentials not working

Credentials are hardcoded in `docker-compose.yml` as `minioadmin / minioadmin`. To change:
```bash
# Edit docker-compose.yml, then:
docker compose down -v
docker compose up -d
```

---

## Production Checklist

- [ ] Set `STIXDB_API_KEY` to a strong secret
- [ ] Set `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`
- [ ] Enable `STIXDB_ENABLE_TRACES=true` for audit trail
- [ ] Enable `STIXDB_BACKUP_ENABLED=true` for file backup
- [ ] Review `STIXDB_AGENT_LINEAGE_SAFE_MODE=true` (preserves source nodes)
- [ ] Configure `STIXDB_LOG_LEVEL=WARNING` or `ERROR` for production
- [ ] Set up monitoring: check logs, metrics, traces regularly
- [ ] Plan backup strategy (PostgreSQL, MinIO)
- [ ] Test failover: stop container, verify data persists, restart
- [ ] Document collection names and their purposes
- [ ] Set up alerting on container health checks

---

## Moving from Local to Production

If you started with [QUICKSTART.md](QUICKSTART.md) (KuzuDB local), you can migrate to production:

### Export from KuzuDB

```python
# Read all nodes from local KuzuDB
config_local = StixDBConfig(
    storage=StorageConfig(mode=StorageMode.KUZU, kuzu_path="./agent_memory")
)

async with StixDBEngine(config_local) as engine:
    all_nodes = await engine.list_nodes("my_agent")
    # Save to JSON or CSV
```

### Import to Neo4j

```python
# Write to Docker+Neo4j instance
config_docker = StixDBConfig(
    storage=StorageConfig(
        mode=StorageMode.NEO4J,
        neo4j_uri="bolt://localhost:7687",
    )
)

async with StixDBEngine(config_docker) as engine:
    for node in all_nodes:
        await engine.store("my_agent", **node)
```

Or use the REST API and Python SDK to pull from one and push to the other.

---

## Next Steps

- **Learn more**: See [README.md](README.md) for architecture & concepts
- **Customize**: Adjust agent parameters in `.env`
- **Scale**: Run multiple collections with different configurations
- **Integrate**: Connect your applications via REST API or SDK
- **Monitor**: Set up observability on traces and metrics


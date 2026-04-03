<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" />
  <img src="https://img.shields.io/badge/async-httpx-orange?style=flat-square" />
</p>

# 🚀 stixdb-sdk — Python Client for StixDB

The easiest way to talk to your **StixDB Agentic Context Database**.

---

## 1. Installation

```bash
pip install stixdb-sdk
```

---

## 2. Quick Start

Ensure a StixDB server is running (use `stixdb serve --port 4020` if you have `stixdb-engine` installed).

```python
from stixdb_sdk import StixDBClient

# 1. Connect to your StixDB server
with StixDBClient(base_url="http://localhost:4020") as client:

    # 2. Store a memory
    client.memory.store(
        "my_agent", 
        content="Our project launch is June 1st, 2026",
        node_type="fact",
        tags=["deadline"]
    )

    # 3. Add an entire folder of PDFs or Markdown files
    client.memory.ingest_folder("my_agent", folder_path="./knowledge_base", recursive=True)

    # 4. Search and get ranked results (fast, no LLM needed)
    results = client.search.create("launch deadline", collection="my_agent", max_results=3)
    for hit in results["results"]:
        print(hit["snippet"])

    # 5. Ask a question and get a reasoned answer (cited sources included!)
    response = client.query.ask("my_agent", question="When's the launch and what's next?")
    print(f"AI Answer: {response['answer']}")
    print(f"AI Reasoning: {response['reasoning_trace']}")
```

---

## 📂 SDK Features

### Memory Management (`client.memory`)
- **`store`**: Add one fact at a time.
- **`bulk_store`**: Add many memories fast.
- **`upload`**: Upload a single PDF, text, or markdown file.
- **`ingest_folder`**: Read an entire directory.
- **`list`/`get`/`delete`**: Manage your memories manually.

### Query & Search (`client.query` & `client.search`)
- **`ask`**: Grounded answers using your private data.
- **`retrieve`**: Find relative facts without using an LLM.
- **`search`**: Advanced search across multiple collections.

### 🔌 OpenAI Compatibility
StixDB is a drop-in replacement for OpenAI’s chat endpoints. Just point the official `openai` Python library's `base_url` to `http://your-server:4020/v1` and use your collection name as the `model`.

---

## ⚡ Async Support

For high-performance applications, use the async client:

```python
import asyncio
from stixdb_sdk import AsyncStixDBClient

async def main():
    async with AsyncStixDBClient(base_url="http://localhost:4020") as client:
        await client.memory.store("async_agent", content="Fast as light!")
        answer = await client.query.ask("async_agent", question="How fast?")
        print(answer["answer"])

asyncio.run(main())
```

---

## 📖 Deep Dives

- **[Examples](../sdk/examples/)** — Runnable code for common patterns.
- **[Main Project README](../README.md)** — Core engine design.
- **[Architecture Guide](../doc/STIXDB_COMPREHENSIVE_GUIDE.md)** — How the 7-phase retrieval pipeline works.

---

## Contributing & Development
- For developer guides and release checklists, see **[DEVELOPMENT.md](../DEVELOPMENT.md)**.
- Report issues on our main repository.

### License
MIT — see **[LICENSE](../LICENSE)**.

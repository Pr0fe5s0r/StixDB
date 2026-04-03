# SDK Usage

## Purpose

StixDB includes a lightweight Python SDK for applications that want a small typed wrapper around the HTTP API instead of making raw `httpx` calls.

The SDK covers the main app-facing surfaces:

- health
- memory CRUD
- folder ingestion from a local path
- retrieval
- question answering
- search

## Package Name

The SDK package is installed and imported as:

```python
import stixdb_sdk
```

Main exports:

- `StixDBClient`
- `AsyncStixDBClient`

## Layout

SDK folder structure:

- `sdk/src/stixdb_sdk/`
  installable package

- `sdk/examples/`
  runnable usage examples

- `sdk/README.md`
  SDK quickstart

The `src/` layout prevents collisions with the main app package, which is also named `stix`.

## Installation

From the repo root:

```bash
pip install -e sdk
```

## Synchronous Usage

```python
from stixdb_sdk import StixDBClient

with StixDBClient(base_url="http://localhost:4020", api_key="my-secret-key") as client:
    health = client.health()
    print(health)

    stored = client.memory.store(
        "demo",
        content="StixDB is an agentic context database.",
        source="manual",
        tags=["intro"],
    )
    print(stored)

    answer = client.query.ask(
        "demo",
        question="What is StixDB?",
    )
    print(answer)
```

## Asynchronous Usage

```python
from stixdb_sdk import AsyncStixDBClient

async def main():
    async with AsyncStixDBClient(base_url="http://localhost:4020", api_key="my-secret-key") as client:
        health = await client.health()
        print(health)

        results = await client.search.create(
            "project deadlines",
            collection="demo",
            include_heatmap=True,
            sort_by="hybrid",
        )
        print(results)
```

## API Areas

### `client.health()`

Checks server health via `/health`.

### `client.memory`

Available operations:

- `store(...)`
- `bulk_store(...)`
- `list(...)`
- `get(...)`
- `delete(...)`
- `upload(...)`
- `ingest_folder(...)`

These wrap the collection memory CRUD endpoints.

`ingest_folder(...)` is the convenience option for the workflow:

- point the SDK at a local folder
- let it walk supported text-like files
- upload them one by one for server-side ingestion
- optionally choose `auto`, `legacy`, or `docling` parsing behavior

### `client.query`

Available operations:

- `ask(...)`
- `retrieve(...)`

Use:

- `ask(...)` for synthesized answers
- `retrieve(...)` for raw retrieval without reasoning

Important:

- `client.query.ask(...)` wraps the REST ask route
- `stream`, `thinking`, and `verbose` are OpenAI-compatible chat options, not SDK `ask(...)` arguments
- use an OpenAI client against `/v1/chat/completions` when you want streaming or StixDB-specific OpenAI extensions

### `client.search`

Available operation:

- `create(...)`

This wraps the product-style `POST /search` API.

## Examples

SDK example scripts live in:

- `sdk/examples/health_check.py`
- `sdk/examples/query_ask.py`
- `sdk/examples/store_and_search.py`
- `sdk/examples/async_usage.py`
- `sdk/examples/ingest_folder_openai_chat.py`

Run them after installing the SDK:

```bash
python sdk/examples/health_check.py
python sdk/examples/query_ask.py
python sdk/examples/store_and_search.py
python sdk/examples/async_usage.py
python sdk/examples/ingest_folder_openai_chat.py
```

## Notes

- The SDK is intentionally lightweight and does not try to hide the core HTTP concepts.
- It is designed to stay close to the REST API surface so new endpoints can be added easily.
- For OpenAI-compatible chat streaming, use the OpenAI client against StixDB’s `/v1` routes instead of this SDK.
## Recommended Combined Workflow

For the common workflow of ingesting a local folder and then asking questions with streaming:

1. Use `client.memory.ingest_folder(...)` from the SDK.
2. Point an OpenAI client at `http://<host>:4020/v1`.
3. Set `model` to the StixDB collection name.
4. Use `stream=True` and pass `verbose` or `thinking` through `extra_body` when needed.

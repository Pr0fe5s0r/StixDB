# OpenAI Compatibility

## Purpose

StixDB includes an OpenAI-compatible API layer so existing OpenAI-style clients can use StixDB with minimal changes.

This means applications can often switch from:

- OpenAI-hosted chat endpoints

to:

- StixDB-hosted memory-backed chat endpoints

just by changing `base_url` and `model`.

## Routes

File:
- `stix/api/routes/openai.py`

Main endpoints:

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/embeddings`

## Model Mapping

In StixDB, the OpenAI `model` field maps to a StixDB collection name.

Example:

```json
{
  "model": "bitcoin",
  "messages": [
    {"role": "user", "content": "What is StixDB?"}
  ]
}
```

This means:

- use the `bitcoin` collection as the memory source
- retrieve context from that collection
- answer from that memory

## `/v1/models`

This endpoint returns the available collection names as model ids.

That allows OpenAI-style clients to discover available memory spaces.

## `/v1/chat/completions`

This endpoint is the main compatibility route.

### Supported request fields

- `model`
- `messages`
- `stream`
- `temperature`
- `max_tokens`
- `user`
- `thinking`
- `verbose`

### StixDB-specific additions

#### `user`

Used as a session id for multi-turn chat history.

#### `thinking`

Enables recursive multi-hop search mode.

This is a StixDB extension and is not part of the base OpenAI chat schema.

#### `verbose`

Enables progress messages during streaming.

This is also StixDB-specific and is best passed through `extra_body` when using OpenAI SDK clients.

## Streaming Behavior

Streaming uses SSE with an OpenAI-like `chat.completion.chunk` response shape.

The route:

- emits an initial assistant-role chunk
- forwards streamed answer deltas
- emits a final stop chunk
- finishes with `[DONE]`

This is designed to work well with standard OpenAI client libraries.

## `/v1/embeddings`

StixDB also exposes an embeddings-style endpoint.

This allows callers to integrate with an OpenAI-like embeddings surface, though operationally it is backed by StixDB’s configured embedding pipeline.

## Compatibility Caveats

StixDB is OpenAI-compatible, not OpenAI-identical.

Important differences:

- `model` means collection name, not a hosted foundation model id
- answer quality depends on the collection’s stored memory
- `thinking` and `verbose` are StixDB-specific
- structured search and memory retrieval happen before generation

## Example Client Usage

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://192.168.109.133:4020/v1",
    api_key="my-secret-key",
)

stream = client.chat.completions.create(
    model="bitcoin",
    messages=[{"role": "user", "content": "What is StixDB?"}],
    stream=True,
    extra_body={"verbose": True},
)

for chunk in stream:
    content = chunk.choices[0].delta.content
    if content:
        print(content, end="", flush=True)
```

## Why This Layer Matters

This compatibility layer makes it easier to:

- reuse existing client code
- plug StixDB into OpenAI-based tooling
- test StixDB with familiar SDKs
- expose memory-backed chat without inventing a brand-new client protocol

## Recommended Workflow

For the common workflow of ingesting local documents and then asking questions:

1. Use the StixDB SDK for local folder ingestion and CRUD.
2. Use the OpenAI-compatible `/v1/chat/completions` route for chat semantics and streaming.
3. Pass StixDB-specific options like `thinking` and `verbose` through `extra_body` when using OpenAI SDK clients.

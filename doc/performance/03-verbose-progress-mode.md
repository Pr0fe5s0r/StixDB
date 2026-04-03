# Verbose Progress Mode

## Purpose

Even after streaming is technically fixed, users can still experience a noticeable wait before the first answer token because StixDB must:

- run retrieval
- prepare context
- wait for model first-token latency

Verbose progress mode improves perceived responsiveness by emitting short progress updates while that work happens.

## API Surface

File:
- `stix/api/routes/openai.py`

New request field on `ChatCompletionRequest`:

- `verbose: bool = False`

This keeps standard OpenAI-compatible behavior unchanged by default.

## Behavior

When:

- `stream=true`
- `verbose=true`

the route emits progress messages into the same SSE stream before and during answer generation.

### Current progress messages

1. Immediately after the assistant role chunk:

`Searching memory graph...`

2. When a `node_count` event is received:

`Retrieved N source excerpts. Generating answer...`

After that, normal answer deltas continue streaming as usual.

## Why This Is Opt-In

OpenAI-compatible clients often assume streamed `delta.content` is only answer text.

If progress text were always included, some clients might:

- display progress text as if it were part of the actual answer
- persist it into chat history
- use it in downstream parsing incorrectly

Making it opt-in solves that:

- default mode stays clean
- debugging and operator-facing clients can enable visibility

## Example Usage

Using the OpenAI Python client:

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

## Design Notes

Verbose mode is intentionally lightweight:

- no separate event type
- no extra protocol
- no client-side special handling required

It simply emits progress text as regular streamed content.

This keeps compatibility broad, especially for clients already built around OpenAI-style delta streaming.

## Test Coverage

File:
- `tests/test_openai_api.py`

There is a focused test that verifies:

- verbose mode emits progress text
- node count progress appears when present
- normal answer content still streams afterward

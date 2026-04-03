# Streaming Overview

## Goal

The main goal of the streaming work was to make StixDB behave like a real token-streaming API for OpenAI-compatible clients:

- open the SSE stream immediately
- forward user-visible content as soon as the model emits deltas
- avoid buffering the answer until the end of generation

## What Was Wrong Before

The original streaming path had two separate issues.

### 1. The HTTP stream opened, but the answer did not become visible early

The route in `stix/api/routes/openai.py` opened an SSE stream quickly, but the user often saw nothing meaningful for several seconds.

That made the stream technically alive but practically feel buffered.

### 2. The reasoner stream depended on XML-like tags

`stix/agent/reasoner.py` used a tagged stream format and parsed sections like:

- `<answer>...</answer>`
- `<reasoning>...</reasoning>`
- `<status>...</status>`

This meant StixDB waited for parseable tagged output before surfacing user-visible text.

If the model:

- delayed the answer section
- emitted reasoning first
- produced malformed or partial tags

then the client either got nothing for a long time or only got one late burst.

### 3. The engine dropped early non-answer chunks

`stix/engine.py` originally favored final `answer` chunks and was willing to ignore or delay other streamed content.

Even if the upstream model was sending text, StixDB could still keep the client waiting.

## Current Design

The live stream path now follows a simpler rule:

- if the provider emits text deltas, StixDB forwards them immediately

### OpenAI-compatible route

File:
- `stix/api/routes/openai.py`

Behavior:

- emits an initial assistant-role chunk
- uses a stable `chatcmpl-*` id across the stream
- forwards each chunk as SSE data
- ends with `finish_reason="stop"` and `[DONE]`
- disables proxy buffering with response headers

Important headers:

- `Cache-Control: no-cache, no-transform`
- `Connection: keep-alive`
- `X-Accel-Buffering: no`

### Reasoner streaming

File:
- `stix/agent/reasoner.py`

Behavior:

- no longer requires XML tags in the hot stream path
- requests plain natural-language streaming output
- forwards raw `delta.content` from the provider immediately as `answer` chunks
- still accumulates `raw_response` for end-of-stream fallback and parsing

### Engine streaming

File:
- `stix/engine.py`

Behavior:

- consumes streamed chunks from the reasoner
- accumulates the final answer for session history
- still supports metadata fallback if the final stream needs parsing or reconstruction

## Why This Works Better

This design removes the biggest source of user-visible delay:

- StixDB no longer waits for tag boundaries or final answer sections
- StixDB no longer needs the model to perfectly follow a formatting contract to show text
- the client now sees incremental content when the upstream model actually streams incremental deltas

## Remaining Latency Sources

If first visible content is still slow, the likely causes are now:

- retrieval latency before the model call
- upstream model queue time
- provider-side first-token latency

That is a much better state than before, because the remaining delay is mostly outside the StixDB chunk-forwarding logic.

## Example Outcome

After the raw-delta change, a benchmark run showed:

- immediate stream open
- multiple content chunks instead of one late final burst
- real incremental answer delivery

That confirmed the streaming bug was not just transport-related; it was caused by application-level gating inside StixDB.

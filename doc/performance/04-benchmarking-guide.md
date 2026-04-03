# Benchmarking Guide

## Purpose

`scripts/benchmarks/benchmark_streaming.py` was created to measure where latency actually comes from in the StixDB chat path.

It helps separate:

- basic server health latency
- retrieval latency
- non-stream completion latency
- stream startup latency
- first visible content latency
- full stream completion time

## File

- `scripts/benchmarks/benchmark_streaming.py`

## Default Target

The script defaults to:

- base URL: `http://192.168.109.133:4020`
- API key: `my-secret-key`

These defaults can be overridden with command-line flags.

## Metrics Collected

### Health

Calls `/health` and measures:

- HTTP status
- server availability latency

### Model discovery

Calls `/v1/models` and measures:

- list-models latency
- available collection/model ids

### Retrieval

Calls:

- `/collections/{collection}/retrieve`

This isolates retrieval cost without LLM synthesis.

Reported fields include:

- `latency_ms`
- result count
- top scores
- top node ids

### Non-stream chat

Calls:

- `/v1/chat/completions` with `stream=false`

Measures total end-to-end latency for a normal blocking request.

### Stream chat

Calls:

- `/v1/chat/completions` with `stream=true`

Measures:

- `ttfb_ms`
  Time until the HTTP streaming response is available.

- `first_sse_ms`
  Time until the first SSE line arrives.

- `first_content_ms`
  Time until the first user-visible `delta.content` arrives.

- `total_ms`
  Total streaming request duration.

- `chunk_count`
  Total number of SSE JSON chunks processed.

- `content_chunk_count`
  Number of chunks that actually carried visible content.

## Example Commands

Basic run:

```bash
python scripts/benchmarks/benchmark_streaming.py
```

JSON output:

```bash
python scripts/benchmarks/benchmark_streaming.py --json
```

Specific model:

```bash
python scripts/benchmarks/benchmark_streaming.py --model bitcoin
```

Custom prompt:

```bash
python scripts/benchmarks/benchmark_streaming.py --model demo --prompt "What is StixDB? Answer in one short sentence."
```

## How To Interpret Results

### Case 1: low TTFB, high first_content

This means:

- transport is fine
- the delay is likely in retrieval, model first-token time, or server-side chunk gating

### Case 2: high retrieval, high total

This means:

- retrieval is a meaningful bottleneck
- batching, caching, or lowering search depth will help

### Case 3: zero content chunks

This means:

- the stream may be technically open
- but visible answer text is not being emitted
- likely causes are model formatting problems or application-level buffering

### Case 4: many content chunks, but late first content

This means:

- true streaming is working
- but first-token latency remains high
- likely causes are retrieval and provider first-token delay

## Example Evolution During This Work

The benchmark was used to verify three important states:

1. Before retrieval batching:
   retrieval was taking several seconds.

2. After retrieval batching:
   retrieval dropped significantly.

3. After raw-delta streaming:
   the stream began producing many visible chunks instead of a late final burst.

## Recommended Usage

Use this script after any change to:

- retrieval logic
- graph backend
- vector backend
- streaming route
- provider/model configuration

It is especially useful for catching the difference between:

- "SSE is open"
- and
- "the user is actually seeing tokens"

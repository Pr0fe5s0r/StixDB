# Retrieval Latency Fix

## Problem Summary

Retrieval latency was a major contributor to end-to-end chat latency.

In the measured environment:

- the SSE connection opened quickly
- but first visible content still arrived late

When retrieval-only latency was measured separately, it took several seconds by itself. That showed the problem was not only generation or streaming.

## Root Cause

The hot path used an expensive query pattern for graph-backed storage, especially Neo4j.

### Original flow

`stix/graph/memory_graph.py` did the following:

1. run vector search
2. for each vector hit, call `get_node(...)`
3. for each seed node, call `get_neighbours(...)`

With `top_k=15`, that can translate into many small graph database round-trips per request.

That pattern is especially expensive when:

- vector search is local/in-memory
- graph storage is remote or slower than memory
- the backend is Neo4j and each lookup opens work on the driver/session path

## Environment-Specific Observation

The active configuration was effectively:

- graph storage: Neo4j
- vector backend: in-memory

That means vector retrieval was fast, but graph hydration and neighbor expansion still paid database round-trip costs.

## Fix

We reduced the number of storage round-trips by batching the expensive parts.

### Storage interface changes

File:
- `stix/storage/base.py`

Added:

- `get_nodes(node_ids, collection)`
- `get_neighbours_for_nodes(node_ids, collection, ...)`

These methods provide a batch-friendly abstraction while still allowing simpler backends to implement fallback loops.

### Neo4j backend optimization

File:
- `stix/storage/neo4j_backend.py`

Added:

- batch node lookup using `UNWIND`
- batch neighbor expansion using `UNWIND` and grouped results

This turns many small queries into a much smaller number of larger, more efficient queries.

### Other backends

Files:

- `stix/storage/networkx_backend.py`

These were updated for interface compatibility. The batch methods are implemented there too, though the biggest production benefit came from the Neo4j path.

### Retrieval pipeline update

File:
- `stix/graph/memory_graph.py`

Changes:

- `semantic_search()` now hydrates vector hits with one batched `get_nodes(...)`
- `semantic_search_with_graph_expansion()` now expands seed nodes with `get_neighbours_for_nodes(...)`

## Performance Impact

Observed benchmark improvement on the live environment:

- retrieval-only latency dropped from roughly `3678 ms` to roughly `1875-2234 ms`

That is a major improvement and directly reduces:

- first-token latency
- full-response latency
- overall user wait time

## Additional Retrieval Notes

The retrieval pipeline still does more than vector similarity alone:

- semantic search
- graph expansion
- reranking
- context truncation

So even after batching, retrieval is not free. If more optimization is needed later, likely next levers are:

- lower `top_k`
- lower graph expansion depth for streaming chat
- lower number of context nodes for fast-path streaming requests
- cache repeated retrievals for identical recent queries

## Why This Change Was Safe

The functional behavior stayed the same:

- same retrieval logic
- same scoring model
- same graph expansion semantics

The main difference is that the database is now asked for the same information in fewer calls.

# Search API

## Purpose

The Search API is StixDB’s product-style retrieval interface.

Unlike chat completion, it does not ask the model to synthesize an answer. Instead, it returns ranked memory results directly.

This is useful for:

- search UIs
- research workflows
- debugging retrieval quality
- custom reasoning pipelines
- analytics over memory relevance

## Route

File:
- `stix/api/routes/search.py`

Endpoint:

- `POST /search`

## Search Flow

For each query, the Search API does the following:

1. validate collections and query shape
2. run retrieval on one or more collections
3. gather raw ranked nodes from `engine.retrieve(...)`
4. filter results
5. transform them into search result objects
6. sort them by the requested strategy
7. return grouped results

## Retrieval Layer Underneath

The Search API uses the same core retrieval pipeline as the rest of StixDB:

- embed query
- semantic vector search
- graph expansion
- rerank candidates

That means search results are not limited to direct vector hits; graph neighbors can be surfaced too depending on depth.

## Request Shape

Important request fields:

- `query`
  single query string or a list of up to 5 queries

- `collection`
  search one collection

- `collections`
  search multiple collections

- `max_results`
  results returned per query

- `top_k`
  retrieval fan-out before filtering and ranking

- `threshold`
  minimum semantic similarity

- `depth`
  graph expansion depth

- `source_filter`
  allowlist or denylist by source name

- `tag_filter`
  match tags

- `node_type_filter`
  restrict by node type

- `tier_filter`
  restrict by memory tier

- `max_chars_per_result`
  controls snippet size

- `include_metadata`
  include node metadata in each result

- `include_heatmap`
  include memory heat/temperature metrics

- `sort_by`
  one of `relevance`, `heat`, or `hybrid`

## Result Shape

Each result includes fields such as:

- title
- source
- collection
- node_id
- snippet
- score
- node_type
- tier
- importance
- tags
- created_at
- last_accessed
- metadata

Optional:

- `heatmap`

## Heatmap / Memory Temperature

When `include_heatmap=true`, the Search API adds a memory heat summary.

This is calculated from:

- access frequency
- recency
- decay score
- importance
- tier boost

The output includes:

- `heat_score`
- `temperature`
- `recency_score`
- `frequency_score`
- `decay_score`
- `importance_score`
- `tier_score`

This is useful for ranking or UI indicators that care about more than just semantic similarity.

## Sorting Modes

### `relevance`

Sorts by retrieval score.

### `heat`

Sorts by memory heat score.

### `hybrid`

Combines:

- 65% relevance
- 35% heat

This can be helpful when you want results that are semantically relevant and operationally important.

## Multi-Query Mode

If `query` is a list, the API processes each query independently and returns grouped results in the same order.

This is useful for:

- dashboard-style retrieval
- comparative search
- batch query workloads

## Relationship To `/retrieve`

`/collections/{collection}/retrieve` is the lower-level retrieval endpoint.

`/search` adds:

- multi-collection support
- multi-query support
- source/tag/tier/node-type filtering
- snippet shaping
- heatmap generation
- ranking modes

So `/retrieve` is the simpler internal/raw retrieval surface, while `/search` is the more product-facing search surface.

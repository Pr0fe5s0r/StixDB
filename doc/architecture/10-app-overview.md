# App Overview

## What StixDB Is

StixDB is an agentic context database.

At a high level, it is a memory system that stores information as a graph, retrieves relevant context for a question, and can synthesize a grounded answer using an LLM.

The key idea is that StixDB is not just:

- a vector store
- a graph database
- a document chunk store

Instead, it combines all three into a system that behaves like an active memory layer for AI applications.

## Core Product Idea

Traditional RAG systems often look like:

- store chunks
- run vector search
- pass results to an LLM

StixDB goes further by adding:

- graph relationships between memories
- memory tiers such as working, episodic, semantic, and archived
- an autonomous background agent that can reorganize memory over time
- retrieval plus graph expansion before reasoning
- a search API and an OpenAI-compatible chat API on top

## What the App Can Do

### 1. Store memory

You can store:

- facts
- entities
- events
- concepts
- procedures
- summaries

Each memory node can include:

- content
- source
- tags
- metadata
- importance
- tier

### 2. Ingest files

StixDB can ingest files such as:

- text files
- PDF files

During ingestion it chunks the content and stores provenance such as:

- file path
- filename
- page number
- character offsets
- document hash

### 3. Retrieve context

Given a query, StixDB can:

- embed the query
- run semantic vector search
- expand the result set through graph neighbors
- rerank the combined candidates
- select a bounded context set for downstream reasoning

### 4. Answer questions

StixDB can answer questions in two styles:

- standard grounded answer generation
- recursive multi-hop "thinking" mode

The answer is built from retrieved memory rather than from an unconstrained model call.

### 5. Stream answers

StixDB exposes an OpenAI-compatible streaming chat API so clients can consume responses incrementally.

### 6. Search memory directly

The Search API returns ranked memory results without LLM synthesis.

This is useful when the caller wants:

- direct search results
- custom downstream reasoning
- UI search experiences
- analytics and filtering

### 7. Run a background memory agent

Each collection can have an autonomous memory agent that manages the memory graph over time.

The agent can:

- observe accesses
- promote hot items
- consolidate similar memories
- generate summaries
- prune cold or low-value memories

## Who It Is For

StixDB is useful for teams building:

- AI assistants with long-term memory
- research copilots
- agent systems that need persistent context
- domain-specific knowledge systems
- chat products that need grounded retrieval

## Main Interfaces

The app exposes multiple ways to interact with the same core engine:

- REST API for memory CRUD and query operations
- OpenAI-compatible API for chat and embeddings-style workflows
- Search API for ranked memory retrieval
- Python SDK for application integration

## Mental Model

The easiest way to think about StixDB is:

- memory is stored as a graph
- search finds relevant nodes
- the graph adds nearby context
- the reasoner synthesizes an answer
- the background agent continuously improves memory quality

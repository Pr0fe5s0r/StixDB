# StixDB Architecture Diagrams

This document provides visual representations of the core StixDB workflows.

## 1. System Overview

The `StixDBEngine` manages multiple `Collections`. Each collection is an isolated unit with its own graph, agent, and context broker.

```mermaid
graph TD
    User([External User / Agent]) -->|API / SDK| Engine[StixDBEngine]
    
    subgraph collection_1 [Collection: 'default']
        Broker1[ContextBroker]
        Agent1[MemoryAgent]
        Graph1[MemoryGraph]
        Storage1[(Storage Backend)]
        Vector1[(Vector Store)]
        
        Broker1 <--> Agent1
        Broker1 <--> Graph1
        Agent1 <--> Graph1
        Graph1 <--> Storage1
        Graph1 <--> Vector1
    end

    subgraph collection_2 [Collection: 'research']
        Broker2[ContextBroker]
        Agent2[MemoryAgent]
        Graph2[MemoryGraph]
        
        Broker2 <--> Agent2
        Broker2 <--> Graph2
    end

    Engine --> collection_1
    Engine --> collection_2
```

## 2. Query Flow (`ask`)

When a user asks a question, StixDB performs a multi-phase retrieval before synthesizing an answer.

```mermaid
sequenceDiagram
    participant U as User
    participant B as ContextBroker
    participant G as MemoryGraph
    participant V as VectorStore
    participant S as StorageBackend
    participant R as Reasoner
    participant A as MemoryAgent

    U->>B: ask(question)
    B->>G: semantic_search_with_graph_expansion(question)
    G->>V: search(embedding)
    V-->>G: seed_node_ids
    G->>S: get_neighbours(seed_nodes, depth=2)
    S-->>G: context_nodes
    G-->>B: final_candidate_nodes
    B->>B: _rerank(working_memory_boost)
    B->>A: record_access(node_ids)
    B->>G: touch_node(node_ids)
    B->>R: reason(question, nodes)
    R-->>B: answer + reasoning_trace
    B-->>U: ContextResponse
```

## 3. Ingestion Flow

Files and folders are chunked, embedded, and stored as graph nodes.

```mermaid
graph LR
    File[Document / PDF] --> Segmenter[Segmenter]
    Segmenter --> Chunker[Chunker]
    Chunker -->|Text Chunks| Embedder[Embedding Client]
    Embedder -->|Vectors| VectorStore[(Vector Store)]
    Chunker -->|Metadata + Content| Storage[(Graph Storage)]
    Storage -.->|Lineage| File
```

## 4. Autonomous Maintenance Cycle

The `MemoryAgent` runs a continuous background loop to optimize the graph.

```mermaid
stateDiagram-v2
    [*] --> Idle: Wait Interval
    Idle --> Perceive: Collection Activity?
    Perceive --> Plan: Access Patterns
    Plan --> Promote_Demote: Update Tiers
    Promote_Demote --> Consolidate: Merge Similars
    Consolidate --> Prune: Remove Stale
    Prune --> Summarize: Auto-Summarization
    Summarize --> Idle: Updated Trace
```

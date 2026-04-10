# StixDB Docs

This folder documents both the overall StixDB application architecture and the features/fixes added in this iteration of the project.

## Contents

- [Comprehensive Guide](STIXDB_COMPREHENSIVE_GUIDE.md)
  New end-to-end technical breakdown of the system architecture, memory model, and agent cycles. Highly recommended as the first reading.

- [Architecture Diagrams](ARCHITECTURE_DIAGRAMS.md)
  Visual representations of StixDB workflows (Ask, Ingest, Maintenance) using Mermaid diagrams.

- `architecture/00-project-guide.md`
  Primary onboarding guide for open-source readers. Explains the project purpose, core concepts, runtime surfaces, repository map, setup, deployment model, testing strategy, and recommended next docs to read.

- `architecture/10-app-overview.md`
  High-level explanation of what StixDB is, what problems it solves, and the main user-facing capabilities.

- `architecture/11-system-architecture.md`
  Detailed system architecture: engine, graph, agent, broker, reasoner, storage, vector search, API layer, and request flows.

- `architecture/12-repo-organization.md`
  Walkthrough of how the codebase is organized and what lives in each major folder.

- `architecture/13-openai-compatibility.md`
  Explains how StixDB exposes an OpenAI-compatible surface, how `/v1/chat/completions` works, and which behaviors are StixDB-specific.

- `architecture/14-search-api.md`
  Full explanation of the memory search API, ranking model, filters, and response shape.

- `architecture/15-sdk-usage.md`
  How to install, import, and use the Python SDK, including sync and async examples.

- `performance/01-streaming-overview.md`
  Explains how StixDB streaming works now, what was broken before, and how the current raw-delta path behaves.

- `performance/02-retrieval-latency-fix.md`
  Documents the retrieval bottleneck we found, why Neo4j round-trips were expensive, and how batched fetch/expansion fixed it.

- `performance/03-verbose-progress-mode.md`
  Describes the new opt-in `verbose` mode on the OpenAI-compatible chat API for progress updates during streaming.

- `performance/04-benchmarking-guide.md`
  Documents the `scripts/benchmarks/benchmark_streaming.py` and `scripts/benchmarks/benchmark_retrieval.py` tools, the metrics they collect, and how to interpret the numbers.

## Scope

The architecture docs describe the whole app.

If you are new to the repository, start with `architecture/00-project-guide.md` and then continue into `architecture/10-app-overview.md` and `architecture/11-system-architecture.md`.

The session docs describe the code created or changed during the streaming and latency investigation:

- OpenAI-compatible streaming route
- Reasoner streaming path
- Engine streaming path
- Retrieval pipeline and storage batching
- Progress visibility in streaming mode
- Latency benchmark tooling

## Notes

- The benchmark numbers are environment-specific. Treat them as examples and rerun the benchmark when infrastructure or models change.
- The streaming path is now optimized for immediate user-visible output. Structured parsing is retained only as a fallback after the stream completes.

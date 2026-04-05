# Contributing to StixDB

Thanks for your interest — all contributions are welcome: bug reports, features, documentation, examples, and storage/embedding backend integrations.

---

## Getting Started

### Prerequisites

- Python 3.10+
- Git

### Setup

```bash
git clone https://github.com/Pr0fe5s0r/StixDB.git
cd StixDB

python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

Copy the example env and configure it:

```bash
cp .env.example .env
# Edit .env — at minimum set STIXDB_LLM_PROVIDER=none for testing without an API key
```

### Run the tests

```bash
pytest tests/ -v
```

Tests run in heuristic mode (`LLMProvider.NONE`) by default — no API key needed.

---

## Project Structure

```
stix/               Core engine
  agent/            MemoryAgent — AccessPlanner, Consolidator, Worker
  api/              FastAPI server and routes
  context/          ContextBroker (7-phase retrieval) and Reasoner
  graph/            MemoryGraph, node/edge/cluster models
  storage/          StorageBackend implementations (NetworkX, KuzuDB, Neo4j)
                    VectorStore implementations (NumPy, ChromaDB, Qdrant)
                    EmbeddingClient (sentence-transformers, OpenAI, Ollama, custom)
  ingestion/        Document parsing and chunking
  observability/    Structured logging and trace emission

sdk/                Python HTTP client (stixdb-sdk)
  src/stixdb_sdk/     Client, MemoryAPI, QueryAPI, SearchAPI

examples/           Runnable examples
tests/              Automated test suite
doc/                Architecture and performance documentation
```

---

## How to Contribute

### Reporting a bug

Open a [GitHub Issue](https://github.com/Pr0fe5s0r/StixDB/issues/new?template=bug_report.md) with:
- Reproduction steps (minimal code)
- Your environment (Python version, storage/vector backend, OS)
- Full stack trace

### Requesting a feature

Open a [GitHub Issue](https://github.com/Pr0fe5s0r/StixDB/issues/new?template=feature_request.md) describing the problem and your proposed solution.

### Submitting a pull request

1. Fork the repo and create a branch: `feature/my-thing` or `fix/issue-123`
2. Make your changes
3. Add or update tests in `tests/`
4. Run `pytest tests/ -v` — all tests must pass
5. Run `ruff check stix/ sdk/src/ && ruff format --check stix/ sdk/src/`
6. Open a PR with a clear description (use the PR template)

---

## Adding a New Storage Backend

Implement `stix/storage/base.py:StorageBackend` and register it in `stix/config.py` under `StorageMode`. See `stix/storage/networkx_backend.py` for the simplest reference implementation.

## Adding a New Vector Backend

Implement the `VectorStore` protocol in `stix/storage/vector_store.py`. See `MemoryVectorStore` for a minimal reference.

## Adding a New LLM Provider

Extend `stix/agent/reasoner.py` — add a branch in `Reasoner._call_llm` and register the new value in `LLMProvider`.

---

## Code Style

- Formatter: `ruff format` (line length 100)
- Linter: `ruff check`
- Logging: `structlog` — never use `print()` in library code
- Models: Pydantic v2
- Tests: `pytest` + `pytest-asyncio`

---

## Security

Do not open public issues for security vulnerabilities. See [SECURITY.md](SECURITY.md).

---

## License

By contributing you agree that your contributions are licensed under the [MIT License](LICENSE).

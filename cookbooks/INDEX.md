# StixDB Cookbooks - Complete Index

A comprehensive guide to all cookbooks for building applications with StixDB.

## 📚 Cookbook Categories

### Comparison — Legacy vs StixDB
**See the difference with runnable benchmarks**

- [`comparison/legacy_vs_stixdb.py`](comparison/legacy_vs_stixdb.py) — Side-by-side: Plain List vs Naive Vector Store vs StixDB across 4 scenarios

**→ Start here if you want to see why StixDB beats basic RAG**

---

### Vibecoding — Shared Agent Memory
**Persistent memory for LLM-assisted coding sessions**

- [`vibecoding/shared_memory.py`](vibecoding/shared_memory.py) — CLI + Python class for shared memory across agents and sessions
- [`vibecoding/CLAUDE.md`](vibecoding/CLAUDE.md) — Instructions for Claude Code: when and how to call the memory script

**→ Start here if you're using Claude Code, Cursor, or any LLM coding agent**

---

### Core SDK & Engine
**Learn the fundamentals of StixDB**

- [`core-sdk/01_basic_store_retrieve.py`](core-sdk/01_basic_store_retrieve.py) — Start here! Basic memory storage and retrieval
- [`core-sdk/02_agent_tuning.py`](core-sdk/02_agent_tuning.py) — Configure agent behavior, memory tiers, and maintenance
- [`core-sdk/03_local_vs_server.py`](core-sdk/03_local_vs_server.py) — Compare in-memory vs. persistent storage modes

**→ Start with `core-sdk` if you're new to StixDB**

---

### Custom LLM Providers
**Use different LLM models and providers for reasoning**

See [`custom-llm/README.md`](custom-llm/README.md) for detailed comparison.

#### Premium Quality (Best Reasoning)
- [`custom-llm/anthropic.py`](custom-llm/anthropic.py) — Claude Opus for complex reasoning
  - Use when: Quality matters more than cost
  - Models: Claude Opus, Claude 3.5 Sonnet, Claude 3 Haiku

#### Cost-Optimized (Best Balance)
- [`custom-llm/openai_gpt4o.py`](custom-llm/openai_gpt4o.py) — GPT-4o for fast, cost-effective reasoning
  - Use when: Balance of speed, quality, and cost
  - Models: GPT-4o (default), GPT-4 Turbo (powerful), GPT-3.5 Turbo (budget)

#### Privacy-First (Completely Local)
- [`custom-llm/privacy_first_local_llm.py`](custom-llm/privacy_first_local_llm.py) — Ollama for on-premises inference
  - Use when: Privacy, HIPAA, offline required
  - Models: Mistral 7B, Llama2, Neural Chat

#### Intelligent Routing (Cost Optimization)
- [`custom-llm/multi_model_routing.py`](custom-llm/multi_model_routing.py) — Route queries to optimal model based on complexity
  - Use when: Mixed workloads, tight budget
  - Strategy: Simple → GPT-3.5, Standard → GPT-4o, Complex → Claude Opus

---

### Custom Embeddings
**Use different embedding models for semantic search**

See [`custom-embeddings/README.md`](custom-embeddings/README.md) for detailed comparison.

#### General Purpose (Production Default)
- [`custom-embeddings/openai_embeddings.py`](custom-embeddings/openai_embeddings.py) — OpenAI embeddings for general-purpose semantic search
  - Use when: General-purpose, multi-lingual, web-scale
  - Models: text-embedding-3-large (best quality), text-embedding-3-small (fast)

#### Domain-Specialized (Expert Knowledge)
- [`custom-embeddings/domain_specialized_embeddings.py`](custom-embeddings/domain_specialized_embeddings.py) — Embeddings optimized for specific domains
  - Use when: Medical, legal, scientific content
  - Models: BiomedNLP (medical), SPECTER (research), PatentSBERTa (patents)

#### Privacy-First Local (HIPAA/GDPR)
- [`custom-embeddings/privacy_first_local_embeddings.py`](custom-embeddings/privacy_first_local_embeddings.py) — Sentence Transformers for on-premises embedding
  - Use when: Privacy critical, offline, cost-sensitive
  - Models: all-MiniLM-L6-v2 (fast), all-mpnet-base-v2 (quality)

#### Hybrid Search (Maximum Quality)
- [`custom-embeddings/hybrid_search_strategy.py`](custom-embeddings/hybrid_search_strategy.py) — Combine dense embeddings + keyword matching
  - Use when: Named entities, product search, mixed queries
  - Strategy: Semantic (70%) + Keyword (30%)

---

### REST API Integration
**Use StixDB via HTTP API**

- [`rest-api/...`](rest-api/) — HTTP API examples
  - Coming soon: REST client, API integration patterns

---

### Multi-Agent Coordination
**Build systems with multiple agents**

- [`multi-agent/...`](multi-agent/) — Multi-agent patterns
  - Concurrent agents, agent communication, shared memory

---

### LangChain Integration
**Use StixDB as retriever in LangChain applications**

- [`langchain/rag_pipeline.py`](langchain/rag_pipeline.py) — Build RAG pipelines with LangChain
- [`langchain/stixdb_retriever.py`](langchain/stixdb_retriever.py) — Custom LangChain retriever for StixDB

---

### OpenAI-Compatible APIs
**Use with OpenAI-compatible LLM providers**

- [`openai-compatible/with_openai_sdk.py`](openai-compatible/with_openai_sdk.py) — OpenAI SDK examples

---

## 🗺️ Quick Navigation by Use Case

### "I'm New to StixDB"
→ Start with [`core-sdk/01_basic_store_retrieve.py`](core-sdk/01_basic_store_retrieve.py)

### "I Need Privacy/HIPAA Compliance"
→ Use [`custom-llm/privacy_first_local_llm.py`](custom-llm/privacy_first_local_llm.py) + [`custom-embeddings/privacy_first_local_embeddings.py`](custom-embeddings/privacy_first_local_embeddings.py)

### "I Want Best Quality (Cost Not Limited)"
→ Use [`custom-llm/anthropic.py`](custom-llm/anthropic.py) + [`custom-embeddings/openai_embeddings.py`](custom-embeddings/openai_embeddings.py)

### "I Want Cost-Optimized Production"
→ Use [`custom-llm/multi_model_routing.py`](custom-llm/multi_model_routing.py) + [`custom-embeddings/openai_embeddings.py`](custom-embeddings/openai_embeddings.py)

### "I Have Medical/Legal/Scientific Data"
→ Use your preferred LLM + [`custom-embeddings/domain_specialized_embeddings.py`](custom-embeddings/domain_specialized_embeddings.py)

### "I'm Building a Product Search"
→ Use [`custom-embeddings/hybrid_search_strategy.py`](custom-embeddings/hybrid_search_strategy.py)

### "I Want to Build a Chatbot"
→ Start with [`core-sdk/03_local_vs_server.py`](core-sdk/03_local_vs_server.py), then add LLM

### "I'm Integrating with LangChain"
→ See [`langchain/rag_pipeline.py`](langchain/rag_pipeline.py)

---

## 🔄 Decision Tree: Choosing Your Stack

```
Start: What's your priority?

├─ Privacy?
│  ├─ YES → Use local models
│  │       ├─ LLM: privacy_first_local_llm.py (Ollama)
│  │       ├─ Embeddings: privacy_first_local_embeddings.py
│  │       └─ Demo: HIPAA-compliant system
│  │
│  └─ NO → Can use cloud APIs

├─ Specialized Domain? (medical, legal, scientific)
│  ├─ YES → Use domain-specialized embeddings
│  │       ├─ Embeddings: domain_specialized_embeddings.py
│  │       ├─ LLM: Any (Anthropic/OpenAI recommended)
│  │       └─ Demo: Domain-expert search
│  │
│  └─ NO → Use general-purpose embeddings

├─ Budget Tight?
│  ├─ YES → Use cost optimization
│  │       ├─ LLM: multi_model_routing.py (intelligent selection)
│  │       ├─ Embeddings: openai_embeddings.py (small model)
│  │       └─ Demo: Cost-optimized production
│  │
│  └─ NO (budget available)
│       ├─ Quality Critical?
│       │  ├─ YES → Use premium models
│       │  │       ├─ LLM: anthropic.py (Claude Opus)
│       │  │       ├─ Embeddings: openai_embeddings.py (large)
│       │  │       └─ Demo: Premium quality system
│       │  │
│       │  └─ NO → Use balanced models
│       │          ├─ LLM: openai_gpt4o.py (GPT-4o)
│       │          ├─ Embeddings: openai_embeddings.py (small)
│       │          └─ Demo: Balanced production
│       │
│       └─ Named Entities/Products Important?
│          ├─ YES → Use hybrid search
│          │       ├─ Embeddings: hybrid_search_strategy.py
│          │       └─ Demo: Product search
│          │
│          └─ NO → Dense embeddings only
```

---

## 📊 Comparison Tables

### LLM Models (by use case)

| Use Case | Recommended | Cost | Speed | Quality |
|----------|-------------|------|-------|---------|
| **Best Quality** | Claude Opus | $$$ | Medium | ⭐⭐⭐⭐⭐ |
| **Best Balance** | GPT-4o | $$ | Fast | ⭐⭐⭐⭐ |
| **Budget** | GPT-3.5 Turbo | $ | Very Fast | ⭐⭐⭐ |
| **Privacy** | Mistral 7B (Local) | Free | Slow | ⭐⭐⭐ |
| **Cost Optimized** | Multi-Model Routing | $ | Varies | ⭐⭐⭐⭐ |

### Embedding Models (by use case)

| Use Case | Recommended | Cost | Speed | Quality |
|----------|-------------|------|-------|---------|
| **Best Quality** | text-embedding-3-large | $$ | Medium | ⭐⭐⭐⭐⭐ |
| **Fast & Good** | text-embedding-3-small | $ | Fast | ⭐⭐⭐⭐ |
| **Privacy** | all-MiniLM-L6-v2 | Free | Fast | ⭐⭐⭐ |
| **Medical** | BiomedNLP | Free | Medium | ⭐⭐⭐⭐⭐ |
| **Scientific** | SPECTER | Free | Medium | ⭐⭐⭐⭐⭐ |
| **Maximum Recall** | Hybrid (Dense+Sparse) | $$ | Slower | ⭐⭐⭐⭐⭐ |

---

## 🚀 Getting Started (30-minute Quick Start)

### Step 1: Setup (5 min)
```bash
# Clone or download StixDB
pip install "stixdb-engine[local-dev]"

# Export API keys (skip if using local models)
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
```

### Step 2: Run Core Cookbook (5 min)
```bash
python cookbooks/core-sdk/01_basic_store_retrieve.py
```

### Step 3: Try LLM Cookbook (10 min)
```bash
# Choose one based on your setup:
python cookbooks/custom-llm/openai_gpt4o.py          # if you have OpenAI key
# OR
python cookbooks/custom-llm/anthropic.py             # if you have Anthropic key
# OR
python cookbooks/custom-llm/privacy_first_local_llm.py  # if you have Ollama
```

### Step 4: Try Embedding Cookbook (10 min)
```bash
# Choose one:
python cookbooks/custom-embeddings/openai_embeddings.py        # general-purpose
# OR
python cookbooks/custom-embeddings/privacy_first_local_embeddings.py  # local
```

---

## 📖 Learning Path

### Beginner (New to StixDB)
1. Read [`core-sdk/README.md`](core-sdk/) overview
2. Run [`core-sdk/01_basic_store_retrieve.py`](core-sdk/01_basic_store_retrieve.py)
3. Explore: What happens when you change `store()` parameters?

### Intermediate (Ready for Custom Models)
4. Read LLM comparison in [`custom-llm/README.md`](custom-llm/README.md)
5. Run ONE LLM cookbook matching your setup
6. Run ONE embedding cookbook
7. Understand the difference: semantic vs. exact match

### Advanced (Building Applications)
8. Read [`custom-llm/multi_model_routing.py`](custom-llm/multi_model_routing.py) for cost optimization
9. Read [`custom-embeddings/hybrid_search_strategy.py`](custom-embeddings/hybrid_search_strategy.py) for quality
10. Combine patterns for your use case

---

## ✅ Cookbook Checklist

### Core SDK
- [ ] `01_basic_store_retrieve.py` — Memory storage basics
- [ ] `02_agent_tuning.py` — Agent configuration
- [ ] `03_local_vs_server.py` — Storage modes

### Custom LLM
- [ ] `anthropic.py` — Premium quality (Claude Opus)
- [ ] `openai_gpt4o.py` — Cost-optimized (GPT-4o)
- [ ] `privacy_first_local_llm.py` — Privacy-first (Ollama)
- [ ] `multi_model_routing.py` — Cost optimization (Smart routing)

### Custom Embeddings
- [ ] `openai_embeddings.py` — General-purpose semantic search
- [ ] `domain_specialized_embeddings.py` — Medical/legal/scientific domains
- [ ] `privacy_first_local_embeddings.py` — Privacy-first local embeddings
- [ ] `hybrid_search_strategy.py` — Dense + sparse search

### Integration
- [ ] `langchain/rag_pipeline.py` — LangChain integration
- [ ] `openai-compatible/with_openai_sdk.py` — OpenAI SDK compatibility
- [ ] `rest-api/...` — HTTP API usage

---

## 🎯 Production Deployment Checklist

Before going to production:

- [ ] Choose LLM provider (privacy/cost/quality tradeoff)
- [ ] Choose embedding model (same tradeoff)
- [ ] Test with your domain data
- [ ] Measure latency and cost
- [ ] Set up monitoring/logging
- [ ] Configure error handling and retries
- [ ] Implement fallback strategies
- [ ] Document your stack
- [ ] Get team buy-in
- [ ] Plan for updates/model changes

See individual cookbook READMEs for checklist items specific to your choices.

---

## 🆘 Troubleshooting

### Common Issues & Solutions

**"API key not found"**
→ Check environment variables: `echo $OPENAI_API_KEY`

**"Connection refused" (Ollama)**
→ Start Ollama: `ollama serve`

**"Model not found" (Ollama)**
→ Pull model: `ollama pull mistral`

**"Out of memory" (Local embedding)**
→ Use smaller model: `all-MiniLM-L6-v2`

**"Slow inference" (Local LLM)**
→ Use GPU: Check CUDA/ROCm installation

See individual cookbook READMEs for more troubleshooting.

---

## 📚 Additional Resources

- **Configuration Guide**: See [`doc/`](../doc/) for detailed configuration
- **API Reference**: Check `stixdb_sdk` package documentation
- **Examples**: All cookbooks are self-contained, executable examples
- **Community**: Submit issues/PRs for new cookbooks

---

## 🤝 Contributing

Found a useful pattern? Create a cookbook!

Template:
1. Create new file in appropriate category
2. Include docstring with use case
3. Add README section
4. Include setup instructions
5. Make it runnable end-to-end
6. Submit PR

---

## 📝 Notes

- All cookbooks are **standalone and runnable**
- Cookbooks **don't modify shared state** (safe to run)
- API keys should be **exported as environment variables**
- Cookbooks are **organized by concept, not difficulty**

---

Last updated: April 2024

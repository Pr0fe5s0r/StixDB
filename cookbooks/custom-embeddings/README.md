# Custom Embeddings Cookbooks

Comprehensive examples of using different embedding models and strategies with StixDB for semantic search and memory retrieval.

## Included Cookbooks

### 1. **openai_embeddings.py** — OpenAI Embedding Models
Use OpenAI's text-embedding-3 models for semantic search.
- Models: text-embedding-3-large (3072 dims), text-embedding-3-small (512 dims)
- Best for: General-purpose semantic search, multi-lingual content
- Cost: $0.02-0.13 per 1M tokens
- Quality: High (continuously improved by OpenAI)
- Use case: Web-scale applications, diverse content

```bash
export OPENAI_API_KEY=sk-...
python openai_embeddings.py
```

---

### 2. **domain_specialized_embeddings.py** — Domain-Specific Models
Use embeddings fine-tuned for specific domains (medical, legal, scientific).
- Models: BiomedNLP (medical), SPECTER (scientific), PatentSBERTa (patents)
- Best for: Domain-specific search, technical terminology
- Cost: Free (local models)
- Quality: Superior in domain, lower outside
- Use case: Medical records, legal documents, research papers

```bash
python domain_specialized_embeddings.py
```

---

### 3. **privacy_first_local_embeddings.py** — Privacy-First Local Embeddings
Compute embeddings locally with Sentence Transformers - no API calls.
- Models: all-MiniLM-L6-v2 (22M), all-mpnet-base-v2 (429M)
- Best for: Privacy, HIPAA/GDPR compliance, offline, cost savings
- Cost: Free (hardware only)
- Quality: Good to excellent (depending on model)
- Use case: Healthcare, legal, confidential data, on-premises

```bash
pip install sentence-transformers torch
python privacy_first_local_embeddings.py
```

---

### 4. **hybrid_search_strategy.py** — Hybrid Search (Dense + Sparse)
Combine semantic embeddings with keyword matching for best results.
- Strategy: Dense vectors (embeddings) + Sparse vectors (BM25)
- Best for: Mixed query types, named entities, robustness
- Cost: Storage ~2x, minimal latency increase
- Quality: Highest (catches semantic + exact matches)
- Use case: Production systems, technical documentation, product search

```bash
python hybrid_search_strategy.py
```

---

## Quick Comparison

| Embedding | Speed | Cost | Privacy | Quality | Domain |
|-----------|-------|------|---------|---------|--------|
| **OpenAI text-3-small** | Fast | $ | Cloud | ⭐⭐⭐⭐ | General |
| **OpenAI text-3-large** | Medium | $$ | Cloud | ⭐⭐⭐⭐⭐ | General |
| **Sentence Transformers** | Medium | Free | Local | ⭐⭐⭐ | General |
| **BiomedNLP** | Medium | Free | Local | ⭐⭐⭐⭐⭐ | Medical |
| **SPECTER** | Medium | Free | Local | ⭐⭐⭐⭐⭐ | Scientific |
| **Hybrid (Dense+Sparse)** | Slower | $$ | Flexible | ⭐⭐⭐⭐⭐ | General |

---

## Choosing the Right Embeddings

### For Quality (General Purpose)
→ **OpenAI text-embedding-3-large** or **all-mpnet-base-v2**
- Best semantic understanding
- Multi-lingual support
- Well-tested in production

### For Balance (Speed + Quality)
→ **OpenAI text-embedding-3-small** or **all-MiniLM-L6-v2**
- Good quality at faster speed
- Lower cost/compute
- Most common choice

### For Privacy & Cost
→ **Sentence Transformers (Local)**
- Zero API cost
- 100% on-premises
- HIPAA/GDPR compliant
- Works offline

### For Domain Expertise
→ **BiomedNLP** (medical), **SPECTER** (research), **PatentSBERTa** (patents)
- Superior domain understanding
- Better terminology handling
- Specialized vocabulary

### For Maximum Recall
→ **Hybrid Search (Dense + Sparse)**
- Catches both semantic and exact matches
- Best for product search, technical docs
- Slight latency/cost tradeoff

---

## Common Patterns

### Pattern 1: General-Purpose Search
```python
from stixdb import StixDBEngine, StixDBConfig

config = StixDBConfig(
    embedding={
        "provider": "openai",
        "model": "text-embedding-3-small"  # Fast, cost-effective
    }
)
engine = StixDBEngine(config)
```

### Pattern 2: Privacy-Critical
```python
config = StixDBConfig(
    embedding={
        "provider": "sentence_transformers",
        "model": "sentence-transformers/all-MiniLM-L6-v2"  # All local
    }
)
# No data leaves your network
```

### Pattern 3: Medical Specialization
```python
config = StixDBConfig(
    embedding={
        "provider": "sentence_transformers",
        "model": "microsoft/BiomedNLP-PubMedBERT-base-uncased"  # Medical optimized
    }
)
# Superior understanding of medical terminology
```

### Pattern 4: Hybrid for Robustness
```python
# Dense: OpenAI embeddings
# Sparse: BM25 keyword indexing
# Combine with 70% semantic + 30% keyword weight
```

---

## Setup Instructions

### For OpenAI Embeddings
```bash
export OPENAI_API_KEY=sk-...
pip install "stixdb-engine[local-dev]"
python openai_embeddings.py
```

### For Local Embeddings (Sentence Transformers)
```bash
pip install sentence-transformers torch
# Optional: GPU acceleration
pip install torch cuda  # or appropriate CUDA version
python domain_specialized_embeddings.py
```

### For Hybrid Search
```bash
# Requires vector store with sparse search support
pip install "stixdb-engine[local-dev]" qdrant-client
python hybrid_search_strategy.py
```

---

## Embedding Dimensions

Different models produce different vector sizes:

| Model | Dimensions | Use Case |
|-------|-----------|----------|
| text-embedding-3-small | 512 | Fast, compact |
| text-embedding-3-large | 3072 | Maximum quality |
| all-MiniLM-L6-v2 | 384 | Balanced local |
| all-mpnet-base-v2 | 768 | High quality local |
| BiomedNLP | 768 | Medical domain |
| SPECTER | 768 | Scientific papers |

**Higher dimensions = Better quality, More storage, Slower search**

---

## Performance Benchmarks

### Embedding Speed (per 1000 documents)
- OpenAI text-3-small (API): ~30 seconds (batched)
- OpenAI text-3-large (API): ~50 seconds (batched)
- all-MiniLM-L6-v2 (local CPU): ~200 seconds
- all-MiniLM-L6-v2 (local GPU): ~20 seconds
- all-mpnet-base-v2 (local CPU): ~600 seconds
- all-mpnet-base-v2 (local GPU): ~60 seconds

### Search Speed (per query)
- Dense vectors: 10-100ms (depends on vector store)
- Sparse vectors (BM25): 1-10ms
- Hybrid: 20-150ms

### Cost Per 1M Tokens Embedded
- OpenAI text-3-small: $0.02
- OpenAI text-3-large: $0.13
- Local (Sentence Transformers): $0 (after download)

---

## Advanced Topics

### Multi-Vector Strategies
Use multiple embedding models:
```python
# Dense vectors for semantic
embeddings1 = openai_embeddings("text-embedding-3-large")

# Sparse vectors for exact match
embeddings2 = bm25_indexer()

# Combine results
combined = merge(embeddings1, embeddings2, weights=(0.7, 0.3))
```

### Fine-Tuning Embeddings
For best domain performance, fine-tune embeddings:
```python
# 1. Collect domain-specific training pairs
# 2. Fine-tune base model
# 3. Use fine-tuned embeddings in production
```

### Embedding Caching
```python
# Cache embeddings for stable content
cache["document_uuid"] = embedding_vector
# Update only on document change
```

### Retrieval Optimization
```python
# Use HNSW index for 1M+ vectors
# Use IVF index for very large datasets
# Trade insert speed for query speed
```

---

## Troubleshooting

### "API key not found"
- Set environment: `export OPENAI_API_KEY=sk-...`
- Verify key in OpenAI dashboard

### Model download too slow (Sentence Transformers)
- Download manually: `python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-mpnet-base-v2')"`
- Cache path: `~/.cache/huggingface/hub/`

### Out of memory (local embeddings)
- Switch to smaller model: `all-MiniLM-L6-v2` (22M)
- Use CPU: `device="cpu"`
- Batch smaller documents

### Poor search quality
- Switch to larger embeddings: `text-embedding-3-large`
- Use domain-specific: `BiomedNLP` for medical
- Add hybrid search for robustness

---

## When to Use Each

**Use OpenAI Embeddings when:**
- General-purpose search
- Multi-lingual content
- Don't mind cloud storage
- Want state-of-art quality

**Use Sentence Transformers when:**
- Privacy critical
- Offline required
- Cost sensitive
- On-premises deployment

**Use Domain-Specific when:**
- Medical/legal/scientific content
- Specialized terminology
- Domain performance matters
- You have 10k+ domain docs

**Use Hybrid Search when:**
- Mixed query types
- Named entities important
- Product/technical search
- Maximum recall needed

---

## Recommendations by Use Case

| Use Case | Embedding | Reason |
|----------|-----------|--------|
| General Q&A | OpenAI text-3-small | Fast, cost-effective |
| Medical records | BiomedNLP + Local | Privacy + domain expertise |
| Legal documents | all-mpnet-base-v2 + Local | Privacy, good quality |
| E-commerce | Hybrid search | Catch brands, features, specs |
| Research papers | SPECTER | Scientific understanding |
| Offline app | Sentence Transformers | Works without internet |
| ChatGPT alternative | OpenAI + Local hybrid | Balances quality and control |

---

## Related Resources

- [OpenAI Embeddings Docs](https://platform.openai.com/docs/guides/embeddings)
- [Sentence Transformers Models](https://www.sbert.net/docs/pretrained_models.html)
- [Hugging Face Models](https://huggingface.co/models)
- [Vector Database Comparison](https://blog.qdrant.io/)
- [StixDB Configuration](../../doc/)

---

## Contributing

Have a useful embedding strategy? Submit a PR with a new cookbook!

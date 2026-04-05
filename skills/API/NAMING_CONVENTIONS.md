# Naming & Comparison Conventions for STIX Cookbooks & Skills

## Overview
When creating cookbooks and skills, we avoid directly naming competing services. Instead, we describe them generically to show similarity without endorsing or directly referencing them.

---

## ❌ Don't Do This

**Avoid direct naming of competing services:**
```python
# ❌ Bad - directly names competitor
# Step 6: Generate answer with LLM (Sonar API)
response = await engine.ask(...)

# ❌ Bad - directly compares to named service
# Like Perplexity, we support semantic search
query_results = client.search.create(...)
```

---

## ✅ Do This Instead

**Use generic descriptions that don't name competitors:**

```python
# ✅ Good - generic description
# Step 5: Generate answer using agentic reasoning
response = await engine.ask(...)

# ✅ Good - describes capability without naming
# Support semantic search with reasoning
# Similar to modern search-based systems
query_results = client.search.create(...)
```

---

## Pattern: Showing Similarity Without Naming

### Approach 1: Generic Description
```python
# ❌ Don't: "Like SearchAPI X, we provide..."
# ✅ Do: "We support similar capabilities to..."

# ✅ Good Examples:
"Similar to search-based reasoning systems, StixDB combines retrieval with LLM reasoning"
"Like other modern retrieval systems, we support semantic search"
"Comparable to enterprise knowledge bases, StixDB organizes memories by tier"
```

### Approach 2: Feature-Based Comparison
```python
# ❌ Don't: "Competitor Y has feature Z"
# ✅ Do: "Our implementation of feature Z"

# ✅ Good Examples:
"Agentic reasoning: retrieve context, then reason to answer questions"
"Semantic search: find memories based on meaning, not just keywords"
"Multi-tier memory: episodic, semantic, procedural, and summary tiers"
```

### Approach 3: Capability Statement
```python
# ❌ Don't: "Unlike ServiceX, we do..."
# ✅ Do: "We provide..."

# ✅ Good Examples:
"Real-time streaming responses with token-by-token feedback"
"Privacy-first local inference with no external API calls"
"Cost optimization through intelligent model routing"
```

---

## Reference: Generic Term Mappings

When you need to reference similar concepts without naming them:

| Concept | Generic Description |
|---------|-------------------|
| Real-time search API | "Semantic search with retrieval" |
| Perplexity-like reasoning | "Agentic reasoning over retrieved context" |
| Search + reasoning system | "Integrated retrieval-and-reasoning pipeline" |
| Modern LLM search | "Vector-based semantic search with LLM synthesis" |
| Real-time reasoning API | "Streaming agentic question answering" |

---

## Approved Comparisons

We **CAN** compare on features, not naming:

✅ **Allowed:**
- "Supports multi-lingual queries (25+ languages)"
- "Faster inference than CPU-based systems"
- "Lower cost than premium enterprise solutions"
- "Better privacy than cloud-based alternatives"
- "More flexible than fixed-schema databases"

❌ **Not Allowed:**
- "Better than [Specific Service]"
- "Like [Competitor Name]'s approach"
- "Unlike [Service X], we..."
- "Faster than [Named Competitor]"

---

## How to Handle Perplexity & Similar Examples

**Context: Showing Ease of Setup**

When mentioning Perplexity specifically to show "how easy to setup and work with," frame it as:

```python
# ✅ Good - shows ease without endorsement
"Building with StixDB is as straightforward as modern search tools.
Just configure your LLM provider, ingest documents, and start querying."

# ✅ Good - shows simplicity
"Setup is simple: initialize engine → store memories → ask questions
Three steps to get started, similar to modern vector databases."

# ✅ Good - shows capability parity
"Like the best search tools, StixDB handles the complexity so you don't have to:
- Automatic chunking
- Semantic indexing  
- Reasoning synthesis
- Stream responses"
```

---

## When Creating New Cookbooks/Skills

Before publishing, check:

1. **Search for direct service names**
   ```bash
   grep -i "sonar\|perplexity\|openai search\|bing\|google" your_file.py
   ```

2. **Replace with generic descriptions**
   - "Search API" → "Semantic search with retrieval"
   - "Perplexity" → "Modern search-based reasoning systems"
   - Specific service → Generic capability description

3. **Use feature-based language**
   - Instead of: "Like [Service]..."
   - Use: "Supports feature X through [mechanism]"

4. **Test: Read without knowing the competitor**
   - If someone unfamiliar with competitors reads this, would they understand the capability?
   - Does it explain WHAT we do, not comparison to others?

---

## Examples from Our Cookbooks

### ✅ Good Example (OpenAI Embeddings)
```
"OpenAI's text-embedding-3 models for semantic search.
OpenAI embeddings are optimized for general-purpose semantic understanding."
```
✓ Describes capability
✓ Explains why to use it
✓ No comparison to other named services

### ✅ Good Example (Privacy-First Local)
```
"Use sentence-transformers to embed documents locally without sending data to APIs.
All embeddings computed on your machine - no external service calls."
```
✓ Clear benefit statement
✓ Explains the advantage
✓ Doesn't name what you're avoiding

### ✅ Good Example (Hybrid Search)
```
"Combine dense embeddings with sparse vectors for best results.
Hybrid search captures both semantic meaning and exact matches."
```
✓ Explains the approach
✓ Shows the benefit
✓ No comparison to competitors

---

## Summary

**Rule of Thumb:**
- ✅ Name our services, tools, and providers (OpenAI, Anthropic, Ollama)
- ✅ Describe capabilities generically
- ✅ Show feature advantages without naming competitors
- ❌ Don't directly name or compare to competing services
- ❌ Don't use comparative language ("better than," "unlike")

**Result:** Cookbooks/skills focus on what you CAN DO, not comparisons to others.

---

## Files Updated

These files have been updated to follow this convention:
- `/d/STIX/cookbooks/langchain/rag_pipeline.py` - Removed "Sonar API" reference
- `/d/STIX/cookbooks/rest-api/curl_examples.sh` - Removed "Sonar API" reference

All new cookbooks and skills follow these conventions by default.

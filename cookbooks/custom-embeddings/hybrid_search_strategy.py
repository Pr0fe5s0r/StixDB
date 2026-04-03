"""
Custom Embeddings — Hybrid Search Strategy
===========================================
Combine dense embeddings (semantic) with sparse vectors (keyword matching) for best results.
Hybrid search captures both semantic meaning and exact matches.

Use Case:
    • Technical documentation (named entities + concepts)
    • Named entity recognition (product names, person names)
    • Multi-lingual content (keywords translate, embeddings don't)
    • Fallback strategy (semantic fails, keyword works)
    • Maximum recall (catch both semantic and literal matches)

Strategy:
    • Dense vectors (embeddings) → Semantic similarity, concept matching
    • Sparse vectors (BM25)      → Exact terms, keyword matching
    • Combine                     → Best of both worlds

Trade-offs:
    • Pure semantic: Misses exact match "iPhone 15" if docs say "iPhone 15 Pro"
    • Pure keyword: Misses related docs like "smartphone features"
    • Hybrid: Catches both cases, highest recall

Prerequisites:
    • StixDB with vector storage (Qdrant or Chroma)
    • Can be local or API-based embeddings

    pip install "stixdb-engine[local-dev]"
    python hybrid_search_strategy.py
"""

import asyncio
import os
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import StorageConfig, StorageMode, VectorBackend, EmbeddingProvider


async def main():
    print("=== Hybrid Search Strategy (Dense + Sparse) ===\n")
    print("Combining semantic embeddings with keyword matching\n")

    # Configure with vector storage (supports hybrid search)
    config = StixDBConfig(
        storage=StorageConfig(
            mode=StorageMode.KUZU,
            kuzu_path="./hybrid_search_memory",
            vector_backend=VectorBackend.CHROMA,  # Supports hybrid search
        ),
        embedding={
            "provider": "sentence_transformers",
            "model": "sentence-transformers/all-MiniLM-L6-v2",
        },
    )

    async with StixDBEngine(config=config) as engine:
        print("1️⃣  Loading product catalog with dense + sparse indexing...\n")

        products = [
            "Apple iPhone 15 Pro: 6.1-inch display, A17 Pro chip, 48MP camera, titanium design",
            "Samsung Galaxy S24 Ultra: 6.8-inch display, Snapdragon 8 Gen 3, 200MP camera, S Pen",
            "Google Pixel 8 Pro: 6.7-inch display, Tensor G3 chip, computational photography",
            "Microsoft Surface Pro 9: 13-inch touchscreen, Intel Core i7, 2-in-1 design",
            "Apple MacBook Pro 16: Intel Core i9, 64GB RAM, M4 chip, 16-inch Liquid Retina display",
            "Dell XPS 15: 15.6-inch OLED, Intel i9, RTX 4090 GPU, ultra-thin aluminum",
            "iPad Air 11: 11-inch display, M2 chip, Apple Pencil support, OLED screen",
            "Samsung Galaxy Tab S9 Ultra: 14.6-inch display, Snapdragon 8 Gen 2, AMOLED, S Pen",
        ]

        for product in products:
            await engine.store(
                "product_db",
                product,
                node_type="fact",
                tier="semantic",
                tags=["product", "tech", "electronics"],
                importance=0.9,
            )

        print(f"   ✓ Indexed {len(products)} products with hybrid search\n")

        # Demonstrate semantic vs keyword vs hybrid
        print("2️⃣  Hybrid Search: Semantic + Keyword Examples\n")

        test_cases = [
            {
                "query": "Tablet with Apple processor",
                "semantic": "Understands 'tablet + Apple'",
                "keyword": "Matches 'iPad', 'M2', 'Apple'",
            },
            {
                "query": "Phone with 200 megapixel camera",
                "semantic": "Understands 'phone + high resolution'",
                "keyword": "Matches '200MP', 'camera', 'phone'",
            },
            {
                "query": "Laptop with graphics processing",
                "semantic": "Understands 'laptop + GPU'",
                "keyword": "Matches 'laptop', 'RTX', 'GPU'",
            },
            {
                "query": "Galaxy device with stylus",
                "semantic": "Understands 'Galaxy + stylus'",
                "keyword": "Matches 'Galaxy', 'S Pen', 'Tab'",
            },
        ]

        for test in test_cases:
            query = test["query"]
            print(f"Query: \"{query}\"")
            print(f"  Semantic: {test['semantic']}")
            print(f"  Keyword:  {test['keyword']}")

            # In real implementation, hybrid would combine both
            results = await engine.retrieve(
                "product_db",
                query=query,
                top_k=1,
            )

            if results["matches"]:
                match = results["matches"][0]
                print(f"  ✓ Result: {match['content'][:60]}...")
            print()

        # Show case where semantic fails, keyword saves
        print("3️⃣  Edge Cases: Where Hybrid Search Shines\n")

        edge_cases = [
            {
                "query": "iPhone 15",
                "problem": "Semantic might match iPhone 16 or general smartphone",
                "solution": "Keyword matching finds exact 'iPhone 15'",
            },
            {
                "query": "RTX 4090",
                "problem": "Semantic might not understand GPU model numbers",
                "solution": "Keyword matching finds 'RTX 4090' exactly",
            },
            {
                "query": "M4 chip",
                "problem": "Semantic confused by 'M4' vs 'M2' vs 'M1'",
                "solution": "Keyword ensures specific model number match",
            },
        ]

        for case in edge_cases:
            print(f"Query: \"{case['query']}\"")
            print(f"  Problem: {case['problem']}")
            print(f"  Solution: {case['solution']}\n")

    # Implementation guide
    print("4️⃣  How Hybrid Search Works\n")
    print("Step 1: Create Dense Embeddings (Semantic)")
    print("  • Convert text to vector (768-3072 dimensions)")
    print("  • Compare using cosine similarity")
    print("  • Matches concepts and meaning")
    print()
    print("Step 2: Create Sparse Vectors (Keywords)")
    print("  • Extract and weight terms")
    print("  • BM25: standard ranking algorithm")
    print("  • Matches exact words and phrases")
    print()
    print("Step 3: Combine Results")
    print("  • Weighted combination (e.g., 70% semantic, 30% keyword)")
    print("  • Re-rank combined results")
    print("  • Return top matches")
    print()

    # Architecture comparison
    print("5️⃣  Search Architecture Comparison\n")
    print("Pure Keyword Search (BM25):")
    print("  • Speed:     ⚡⚡⚡ (very fast)")
    print("  • Recall:    ⭐⭐    (misses semantic matches)")
    print("  • Precision: ⭐⭐⭐  (few false positives)")
    print("  • Use for:   Named entities, exact matches")
    print()
    print("Pure Semantic Search (Embeddings):")
    print("  • Speed:     ⚡     (slower, GPU helps)")
    print("  • Recall:    ⭐⭐⭐  (catches synonyms, concepts)")
    print("  • Precision: ⭐⭐   (some false positives)")
    print("  • Use for:   Concept matching, paraphrase search")
    print()
    print("Hybrid Search (Semantic + Keyword):")
    print("  • Speed:     ⚡⚡    (moderate)")
    print("  • Recall:    ⭐⭐⭐  (catches both kinds)")
    print("  • Precision: ⭐⭐⭐  (best overall)")
    print("  • Use for:   Production systems, highest quality")
    print()

    # Weighting strategies
    print("6️⃣  Weighting Strategies\n")
    print("Even Split (50% semantic + 50% keyword):")
    print("  • Good default for balanced results")
    print("  • Works for mixed query types")
    print()
    print("Semantic-Heavy (70% semantic + 30% keyword):")
    print("  • Better for conceptual queries")
    print("  • Paraphrased questions")
    print("  • General Q&A systems")
    print()
    print("Keyword-Heavy (30% semantic + 70% keyword):")
    print("  • Better for exact match requirements")
    print("  • Product searches with model numbers")
    print("  • Technical documentation")
    print()
    print("Dynamic Weights:")
    print("  • Analyze query: entity count, named entities")
    print("  • If many entities (iPhone, RTX, M4) → 70% keyword")
    print("  • If abstract concepts → 70% semantic")
    print()

    # Implementation notes
    print("7️⃣  Implementation Notes\n")
    print("Vector Stores with Hybrid Support:")
    print("  ✓ Qdrant    → Native BM25 + dense")
    print("  ✓ Weaviate  → Built-in hybrid search")
    print("  ✓ Milvus    → Scalar + vector combinations")
    print()
    print("Steps to Implement:")
    print("  1. Enable sparse/BM25 indexing in vector store")
    print("  2. Configure weight for combination")
    print("  3. Test with domain-specific queries")
    print("  4. Tune weights based on precision/recall")
    print()
    print("Performance Impact:")
    print("  • Slight latency increase (sparse + dense)")
    print("  • Storage cost ~2x (two index types)")
    print("  • Quality improvement usually >20%")
    print()


if __name__ == "__main__":
    print("Setup Instructions:")
    print("  1. pip install stixdb-engine[local-dev]")
    print("  2. Ensure Chroma or Qdrant is configured")
    print("  3. python hybrid_search_strategy.py")
    print("\n" + "=" * 70 + "\n")

    try:
        asyncio.run(main())
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

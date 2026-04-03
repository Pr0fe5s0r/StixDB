"""
Custom Embeddings — OpenAI Embedding Models
============================================
Use OpenAI's text-embedding-3 models for semantic search and memory retrieval.
OpenAI embeddings are optimized for general-purpose semantic understanding.

Use Case:
    • General-purpose semantic search across diverse content
    • Multi-lingual applications (embeddings support 25+ languages)
    • When you want compatibility with OpenAI models (GPT-4, etc.)
    • Web-scale deployments (proven reliability and performance)
    • Balanced quality and cost (better cost than proprietary options)

Embedding Models Available:
    • text-embedding-3-large   → 3072 dimensions, most capable
    • text-embedding-3-small   → 512 dimensions, fast and cheap

Prerequisites:
    • OpenAI API key: https://platform.openai.com/api-keys
    • export OPENAI_API_KEY=sk-...

    pip install "stixdb-engine[local-dev]"
    python cookbooks/custom-embeddings/openai_embeddings.py
"""

import asyncio
import os
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import (
    StorageConfig, StorageMode, VectorBackend,
    EmbeddingConfig, EmbeddingProvider
)


class EmbeddingConfig:
    """Placeholder - replace with actual config class"""
    def __init__(self, provider, model=None, api_key=None):
        self.provider = provider
        self.model = model
        self.api_key = api_key


async def main():
    print("=== StixDB with OpenAI Embeddings ===\n")

    # Get API key from environment
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY not set")
        print("   export OPENAI_API_KEY=sk-...")
        return

    # Configure with OpenAI embeddings
    config = StixDBConfig(
        storage=StorageConfig(
            mode=StorageMode.KUZU,
            kuzu_path="./openai_embedding_memory",
            vector_backend=VectorBackend.CHROMA,  # Chroma works well with OpenAI
        ),
        embedding=EmbeddingConfig(
            provider=EmbeddingProvider.OPENAI,
            model="text-embedding-3-small",  # Fast and cost-effective
            # or "text-embedding-3-large" for higher quality
            api_key=api_key,
        ),
    )

    async with StixDBEngine(config=config) as engine:
        # 1. Setup: Store product descriptions
        print("1️⃣  Loading product catalog with OpenAI embeddings...\n")

        products = [
            "Wireless noise-cancelling headphones with 40-hour battery life",
            "Ultra-fast USB-C charger supporting 65W power delivery",
            "Stainless steel water bottle with temperature display",
            "Mechanical RGB gaming keyboard with custom switches",
            "4K webcam with auto-focus and built-in microphone",
            "Portable SSD with 2TB storage and 1000MB/s speed",
            "Minimalist desk lamp with adjustable color temperature",
            "Ergonomic mouse with precision tracking sensor",
            "Premium laptop stand with cooling pad",
            "Wireless charging dock for multiple devices",
        ]

        for product in products:
            await engine.store(
                "product_catalog",
                product,
                node_type="fact",
                tier="semantic",
                tags=["product", "tech"],
                importance=0.85,
            )

        print(f"   ✓ Embedded {len(products)} products with OpenAI text-embedding-3-small\n")

        # 2. Example 1: Semantic search (exactly what embeddings excel at)
        print("2️⃣  Semantic search - finding products by meaning...\n")

        queries = [
            "I need something to charge my devices wirelessly",
            "Looking for equipment for gaming",
            "I want a phone charger that's really fast",
            "What do you have for battery life and portability?",
        ]

        for query in queries:
            results = await engine.retrieve(
                "product_catalog",
                query=query,
                top_k=2,
            )
            print(f"Q: {query}")
            for match in results["matches"]:
                print(f"  ✓ {match['content']} (similarity: {match['similarity']:.2f})")
            print()

        # 3. Example 2: Multi-language support
        print("3️⃣  Multi-language semantic search...\n")
        print("OpenAI embeddings support 25+ languages:\n")

        multilingual_queries = [
            ("Necesito un cargador rápido", "Spanish"),
            ("Je veux des écouteurs sans fil", "French"),
            ("Ich brauche einen Monitor", "German"),
        ]

        for query, language in multilingual_queries:
            results = await engine.retrieve(
                "product_catalog",
                query=query,
                top_k=1,
            )
            if results["matches"]:
                match = results["matches"][0]
                print(f"{language}: \"{query}\"")
                print(f"  → {match['content']}\n")

        # 4. Example 3: Vector dimension comparison
        print("4️⃣  Embedding Model Comparison\n")
        print("text-embedding-3-small:")
        print("  • Dimensions: 512")
        print("  • Speed: ~100ms per batch")
        print("  • Cost: $0.02 per 1M tokens")
        print("  • Use when: Speed matters, cost-sensitive")
        print()
        print("text-embedding-3-large:")
        print("  • Dimensions: 3072")
        print("  • Speed: ~150ms per batch")
        print("  • Cost: $0.13 per 1M tokens")
        print("  • Use when: Maximum quality, complex domains")
        print()

        # 5. Example 4: Why embeddings matter
        print("5️⃣  Why OpenAI Embeddings?\n")
        print("✓ Semantic Understanding")
        print("  → \"wireless charger\" matches \"charging dock\"")
        print("  → Not just keyword matching\n")
        print("✓ Language Agnostic")
        print("  → Spanish, French, German, Chinese all work")
        print("  → Same embedding space across languages\n")
        print("✓ Proven Quality")
        print("  → Built on 3-year track record")
        print("  → Used by thousands of applications\n")
        print("✓ Integration Friendly")
        print("  → Works perfectly with GPT-4, Claude")
        print("  → Single vendor for LLM + embeddings\n")

        # 6. Advanced tip
        print("6️⃣  Performance Tips for Production\n")
        print("✓ Batch Embeddings")
        print("  → Embed 100+ texts in single API call")
        print("  → Reduces latency and cost")
        print()
        print("✓ Caching Strategy")
        print("  → Cache embeddings for stable content")
        print("  → Update only when content changes")
        print()
        print("✓ Vector Index")
        print("  → Use HNSW or IVF indexes for 1M+ vectors")
        print("  → Trades insert speed for query speed")
        print()
        print("✓ Hybrid Search")
        print("  → Combine semantic search with keyword matching")
        print("  → Better coverage for named entities")
        print()


if __name__ == "__main__":
    print("Setup Instructions:")
    print("  1. Get API key: https://platform.openai.com/api-keys")
    print("  2. Set env var: export OPENAI_API_KEY=sk-...")
    print("\n" + "=" * 70 + "\n")

    try:
        asyncio.run(main())
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

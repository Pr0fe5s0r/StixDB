"""
Custom LLM — Ollama (Local LLMs)
================================
Use StixDB with Ollama for local LLMs (no API key needed).

Ollama runs LLMs locally: llama2, mistral, phi, neural-chat, etc.

Prerequisites:
    • Install Ollama: https://ollama.ai
    • Start Ollama: ollama serve
    • Pull a model: ollama pull llama2

    pip install "stixdb-engine[local-dev]"
    python cookbooks/custom-llm/ollama_local.py
"""

import asyncio
import os
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import (
    StorageConfig,
    StorageMode,
    ReasonerConfig,
    LLMProvider,
    EmbeddingConfig,
    EmbeddingProvider,
)


async def main():
    print("=== StixDB with Ollama (Local LLMs) ===\n")

    # Configure Ollama
    # Models: llama2, mistral, phi, neural-chat, etc.
    config = StixDBConfig(
        storage=StorageConfig(mode=StorageMode.KUZU, kuzu_path="./ollama_memory"),
        # Use Ollama for reasoning
        reasoner=ReasonerConfig(
            provider=LLMProvider.OLLAMA,
            model="llama2",  # or: mistral, phi, neural-chat, etc.
            ollama_base_url="http://localhost:11434",  # default Ollama port
            temperature=0.2,
            max_tokens=500,
        ),
        # Use local embeddings (already included)
        embedding=EmbeddingConfig(
            provider=EmbeddingProvider.SENTENCE_TRANSFORMERS,
            model="all-MiniLM-L6-v2",
        ),
    )

    async with StixDBEngine(config=config) as engine:
        # 1. Store knowledge base
        print("1️⃣  Storing knowledge base...\n")

        facts = [
            "Python is a high-level programming language",
            "Async/await enables concurrent programming in Python",
            "FastAPI is a modern web framework for Python",
            "AsyncIO library provides async tools in Python",
            "Coroutines are functions that can be paused and resumed",
        ]

        for fact in facts:
            await engine.store(
                "python_kb",
                fact,
                node_type="fact",
                tags=["python", "programming"],
                importance=0.8,
            )

        print(f"   ✓ Stored {len(facts)} facts\n")

        # 2. Search (no LLM cost)
        print("2️⃣  Search (no LLM cost)...\n")

        results = await engine.retrieve(
            "python_kb",
            "What is async in Python?",
            top_k=2,
        )

        print("Q: What is async in Python?\n")
        for res in results:
            print(f"  • [{res['score']:.3f}] {res['content']}\n")

        # 3. Ask with Ollama (local LLM, no API key)
        print("3️⃣  Ask with Ollama (local LLM)...\n")

        response = await engine.ask(
            "python_kb",
            "Explain async/await in Python",
            top_k=3,
        )

        print("Q: Explain async/await in Python\n")
        print(f"A: {response.answer}\n")
        print(f"Confidence: {response.confidence:.2f}\n")

        # 4. Chat with Ollama
        print("4️⃣  Chat with Ollama...\n")

        session_id = "user_123"

        q1 = "What programming language should I learn?"
        response1 = await engine.chat(
            "python_kb",
            message=q1,
            session_id=session_id,
        )
        print(f"Q: {q1}")
        print(f"A: {response1.answer}\n")

        q2 = "Why that one?"
        response2 = await engine.chat(
            "python_kb",
            message=q2,
            session_id=session_id,
        )
        print(f"Q: {q2}")
        print(f"A: {response2.answer}\n")

        # 5. Try different Ollama models
        print("5️⃣  Available Ollama Models\n")
        print("You can use any Ollama model by changing the config:\n")
        print("  Models (run 'ollama pull MODEL' first):")
        print("    • llama2 (7B, 13B, 70B)")
        print("    • mistral (7B, recommended for speed)")
        print("    • phi (2.7B, very fast)")
        print("    • neural-chat (7B)")
        print("    • openchat (3.5B)")
        print("    • dolphin-mixtral (47B, very capable)\n")
        print("Example for Mistral (faster):")
        print("  ReasonerConfig(")
        print("    provider=LLMProvider.OLLAMA,")
        print("    model='mistral',  # <- change this")
        print("  )\n")


if __name__ == "__main__":
    print("Prerequisites:")
    print("  1. Install Ollama: https://ollama.ai")
    print("  2. Start Ollama: ollama serve")
    print("  3. Pull a model: ollama pull llama2")
    print("\n" + "=" * 60 + "\n")

    try:
        asyncio.run(main())
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\nMake sure Ollama is running:")
        print("  ollama serve")

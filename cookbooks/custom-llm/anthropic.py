"""
Custom LLM — Anthropic Claude
=============================
Use StixDB with Anthropic's Claude API.

Prerequisites:
    • Anthropic API key: https://console.anthropic.com
    • export ANTHROPIC_API_KEY=sk-ant-...

    pip install "stixdb-engine[local-dev]"
    python cookbooks/custom-llm/anthropic.py
"""

import asyncio
import os
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import StorageConfig, StorageMode, ReasonerConfig, LLMProvider


async def main():
    print("=== StixDB with Anthropic Claude ===\n")

    # Get API key from environment
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("❌ ANTHROPIC_API_KEY not set")
        print("   export ANTHROPIC_API_KEY=sk-ant-...")
        return

    # Configure Anthropic
    config = StixDBConfig(
        storage=StorageConfig(mode=StorageMode.KUZU, kuza_path="./claude_memory"),
        reasoner=ReasonerConfig(
            provider=LLMProvider.ANTHROPIC,
            model="claude-opus-4-6",  # or: claude-3.5-sonnet, claude-3-haiku
            anthropic_api_key=api_key,
            temperature=0.2,
            max_tokens=1000,
            max_context_nodes=20,
        ),
    )

    async with StixDBEngine(config=config) as engine:
        # 1. Store knowledge base
        print("1️⃣  Storing knowledge base...\n")

        documents = [
            "Claude is Anthropic's AI assistant",
            "Anthropic focuses on AI safety",
            "Constitutional AI is used to train Claude",
            "Claude can process long documents (100k tokens)",
            "Anthropic was founded in 2021",
        ]

        for doc in documents:
            await engine.store(
                "anthropic_kb",
                doc,
                node_type="fact",
                tags=["anthropic", "claude"],
                importance=0.8,
            )

        print(f"   ✓ Stored {len(documents)} documents\n")

        # 2. Search
        print("2️⃣  Search knowledge base...\n")

        results = await engine.retrieve(
            "anthropic_kb",
            "What is Claude?",
            top_k=2,
        )

        print("Q: What is Claude?\n")
        for res in results:
            print(f"  • [{res['score']:.3f}] {res['content']}\n")

        # 3. Ask Claude
        print("3️⃣  Ask Claude about Anthropic...\n")

        response = await engine.ask(
            "anthropic_kb",
            question="What is Anthropic's mission?",
            top_k=3,
        )

        print("Q: What is Anthropic's mission?\n")
        print(f"A: {response.answer}\n")
        print(f"Confidence: {response.confidence:.2f}\n")
        print("Sources:")
        for source in response.sources:
            print(f"  • {source.content}")
            print(f"    (score: {source.score:.3f})\n")

        # 4. Chat with Claude
        print("4️⃣  Multi-turn conversation with Claude...\n")

        session_id = "user_123"

        # Turn 1
        q1 = "What models does Anthropic offer?"
        r1 = await engine.chat(
            "anthropic_kb",
            message=q1,
            session_id=session_id,
        )
        print(f"Q: {q1}")
        print(f"A: {r1.answer}\n")

        # Turn 2
        q2 = "Which one is best for long documents?"
        r2 = await engine.chat(
            "anthropic_kb",
            message=q2,
            session_id=session_id,
        )
        print(f"Q: {q2}")
        print(f"A: {r2.answer}\n")

        # 5. Show available models
        print("5️⃣  Available Claude Models\n")
        print("You can switch between Claude models:\n")
        print("  model='claude-opus-4-6'      # Most capable")
        print("  model='claude-3.5-sonnet'    # Best balance")
        print("  model='claude-3-haiku'       # Fastest, cheapest\n")


if __name__ == "__main__":
    print("Setup Instructions:")
    print("  1. Get API key from: https://console.anthropic.com")
    print("  2. Set env var: export ANTHROPIC_API_KEY=sk-ant-...")
    print("\n" + "=" * 60 + "\n")

    try:
        asyncio.run(main())
    except Exception as e:
        print(f"❌ Error: {e}")
        if "api key" in str(e).lower():
            print("\nMake sure ANTHROPIC_API_KEY is set:")
            print("  export ANTHROPIC_API_KEY=sk-ant-...")

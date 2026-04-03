"""
Custom LLM — OpenAI GPT-4o (Cost-Optimized)
=============================================
Use StixDB with OpenAI's GPT-4o for cost-effective reasoning and fast inference.
This is ideal when you want fast, capable reasoning without premium model costs.

Use Case:
    • Budget-conscious applications needing fast responses
    • Real-time chat applications where latency matters
    • High-volume query processing (GPT-4o is cheaper than Opus)
    • Balanced performance/cost ratio

Prerequisites:
    • OpenAI API key: https://platform.openai.com/api-keys
    • export OPENAI_API_KEY=sk-...

    pip install "stixdb-engine[local-dev]"
    python cookbooks/custom-llm/openai_gpt4o.py
"""

import asyncio
import os
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import StorageConfig, StorageMode, ReasonerConfig, LLMProvider


async def main():
    print("=== StixDB with OpenAI GPT-4o (Cost-Optimized) ===\n")

    # Get API key from environment
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY not set")
        print("   export OPENAI_API_KEY=sk-...")
        return

    # Configure OpenAI GPT-4o for cost optimization
    config = StixDBConfig(
        storage=StorageConfig(mode=StorageMode.KUZU, kuzu_path="./gpt4o_memory"),
        reasoner=ReasonerConfig(
            provider=LLMProvider.OPENAI,
            model="gpt-4o",  # Fast and cost-effective
            openai_api_key=api_key,
            temperature=0.3,  # Lower for more consistent results
            max_tokens=1500,
            max_context_nodes=25,
            timeout_seconds=30.0,  # Shorter timeout for real-time apps
        ),
    )

    async with StixDBEngine(config=config) as engine:
        # 1. Setup: Store customer support knowledge base
        print("1️⃣  Loading customer support knowledge base...\n")

        support_docs = [
            "Refund requests must be made within 30 days of purchase",
            "Shipping to US typically takes 5-7 business days",
            "International shipping takes 10-21 business days",
            "Free shipping on orders over $50",
            "We accept Visa, Mastercard, PayPal, and Apple Pay",
            "Password resets are sent via email within 5 minutes",
            "Account verification requires a valid phone number",
            "Return shipping is free for defective items",
            "We offer 1-year warranty on all electronics",
            "Prime members get 50% off shipping",
        ]

        for doc in support_docs:
            await engine.store(
                "support_kb",
                doc,
                node_type="fact",
                tier="semantic",
                tags=["support", "policy"],
                importance=0.85,
            )

        print(f"   ✓ Stored {len(support_docs)} support policies\n")

        # 2. Example 1: Quick customer inquiry
        print("2️⃣  Fast response to customer inquiry...\n")

        response = await engine.ask(
            "support_kb",
            question="How long does shipping take to the US?",
            top_k=5,
        )

        print("Q: How long does shipping take to the US?")
        print(f"A: {response.answer}\n")
        print("✓ Responded using GPT-4o (fast, cost-effective)\n")

        # 3. Example 2: Complex policy question
        print("3️⃣  Handling complex multi-policy question...\n")

        response = await engine.ask(
            "support_kb",
            question="I'm a Prime member returning a defective item from an international purchase. What are my costs and timeline?",
            top_k=10,
            depth=2,
        )

        print("Q: I'm a Prime member returning a defective item from international purchase...")
        print(f"A: {response.answer}\n")
        print("Reasoning steps:")
        for i, step in enumerate(response.reasoning_trace.split("\n")[:3], 1):
            print(f"  {i}. {step}")
        print()

        # 4. Example 3: Real-time chat (showing GPT-4o's speed advantage)
        print("4️⃣  Real-time chat conversation (GPT-4o latency optimized)...\n")

        chat_responses = []
        questions = [
            "What payment methods do you accept?",
            "What about Apple Pay?",
            "Is there a discount for multiple purchases?",
        ]

        conversation_id = "customer_123"
        for q in questions:
            response = await engine.chat(
                "support_kb",
                message=q,
                conversation_id=conversation_id,
            )
            chat_responses.append(response)
            print(f"Q: {q}")
            print(f"A: {response.text}\n")

        print(f"✓ Completed {len(chat_responses)} turns with GPT-4o\n")

        # 5. Cost comparison notes
        print("5️⃣  GPT-4o Performance Characteristics\n")
        print("Advantages over premium models:")
        print("  • ~70% cheaper than Claude Opus")
        print("  • ~40% cheaper than GPT-4 Turbo")
        print("  • 50-100ms faster average latency")
        print("  • Perfect for real-time applications")
        print("  • Handles complex reasoning well")
        print()
        print("Best for:")
        print("  • Customer support chatbots")
        print("  • High-volume query processing")
        print("  • Cost-sensitive production systems")
        print("  • Real-time chat interfaces")
        print()

        # 6. Show when to use different OpenAI models
        print("6️⃣  OpenAI Model Selection Guide\n")
        print("GPT-4 Turbo       → Maximum reasoning capability (use for complex analysis)")
        print("GPT-4o            → Best balance (default choice)")
        print("GPT-3.5 Turbo     → Fast & cheap (simple queries)")
        print()
        print("Our recommendation: Start with GPT-4o, scale down to 3.5 if budget tight\n")


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

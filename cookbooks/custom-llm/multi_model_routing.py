"""
Custom LLM — Multi-Model Routing Strategy
==========================================
Intelligently route queries to different models based on complexity.
Use fast cheap models for simple queries, powerful models for complex analysis.

Use Case:
    • Cost optimization through intelligent model selection
    • Performance tuning (fast simple queries, thorough complex analysis)
    • Fallback strategy (downgrade if primary model overloaded)
    • Mixed workload environments (simple + complex queries)
    • A/B testing different model capabilities

Strategy:
    • Simple queries (user lookup, quick facts) → GPT-3.5 Turbo (fast, cheap)
    • Standard queries (policy questions) → GPT-4o (balanced)
    • Complex analysis (synthesis, multi-step) → GPT-4 Turbo (powerful)
    • Reasoning tasks (diagnosis, decision support) → Claude Opus (best reasoning)

Prerequisites:
    • OpenAI API key: export OPENAI_API_KEY=sk-...
    • Anthropic API key: export ANTHROPIC_API_KEY=sk-ant-...

    pip install "stixdb-engine[local-dev]"
    python cookbooks/custom-llm/multi_model_routing.py
"""

import asyncio
import os
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import StorageConfig, StorageMode, ReasonerConfig, LLMProvider


async def create_engine_with_model(model_name: str, provider: LLMProvider):
    """Factory function to create engine with specified model."""

    if provider == LLMProvider.OPENAI:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")
    elif provider == LLMProvider.ANTHROPIC:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")
    else:
        api_key = None

    config = StixDBConfig(
        storage=StorageConfig(mode=StorageMode.KUZU, kuzu_path="./multi_model_memory"),
        reasoner=ReasonerConfig(
            provider=provider,
            model=model_name,
            openai_api_key=api_key if provider == LLMProvider.OPENAI else None,
            anthropic_api_key=api_key if provider == LLMProvider.ANTHROPIC else None,
            temperature=0.2,
            max_tokens=1500,
            max_context_nodes=20,
        ),
    )
    return StixDBEngine(config=config)


def classify_query_complexity(question: str) -> str:
    """
    Simple heuristic to classify query complexity.
    In production, you'd use a more sophisticated approach (ML classifier, token count, etc.)
    """

    # Keywords indicating simple lookups
    simple_keywords = ["what is", "how much", "who is", "when", "where", "simple"]

    # Keywords indicating complex reasoning
    complex_keywords = [
        "why", "compare", "analyze", "recommend", "diagnose",
        "synthesize", "trade-off", "evaluate", "strategy", "impact"
    ]

    question_lower = question.lower()

    # Count keyword matches
    simple_score = sum(1 for kw in simple_keywords if kw in question_lower)
    complex_score = sum(1 for kw in complex_keywords if kw in question_lower)

    # Multi-part questions (multiple sentences) are usually complex
    if question.count("?") > 1 or len(question) > 150:
        complex_score += 2

    if complex_score > simple_score:
        return "complex"
    elif simple_score > 0:
        return "simple"
    else:
        return "standard"


async def main():
    print("=== Multi-Model Query Routing ===\n")
    print("Intelligently choosing models based on query complexity\n")

    # Setup knowledge base
    print("1️⃣  Loading knowledge base...\n")

    knowledge = [
        "Customer satisfaction score of 4.5+/5 is excellent",
        "Average customer lifetime value is $2,500",
        "Churn rate above 5% monthly indicates problem",
        "NPS (Net Promoter Score) above 50 is strong",
        "Customer acquisition cost (CAC) should be <3x LTV",
        "Response time under 2 hours keeps customers happy",
        "70% of customers prefer email support",
        "Live chat increases conversion by 20%",
        "Product recommendations increase average order value 15%",
        "Customer retention is 5x cheaper than acquisition",
    ]

    # All models will use same knowledge base
    base_config = StixDBConfig(
        storage=StorageConfig(mode=StorageMode.KUZU, kuzu_path="./multi_model_memory"),
    )

    test_engine = StixDBEngine(base_config)
    async with test_engine:
        for fact in knowledge:
            await test_engine.store(
                "business_kb",
                fact,
                node_type="fact",
                tier="semantic",
                tags=["metrics", "business"],
                importance=0.8,
            )

    print(f"   ✓ Stored {len(knowledge)} business metrics\n")

    # Test queries with varying complexity
    test_queries = [
        {
            "question": "What is a good NPS score?",
            "expected_complexity": "simple",
        },
        {
            "question": "How should we balance customer acquisition vs. retention costs? What metrics matter?",
            "expected_complexity": "complex",
        },
        {
            "question": "Compare email vs. live chat support for customer satisfaction.",
            "expected_complexity": "standard",
        },
        {
            "question": "Why is customer lifetime value important?",
            "expected_complexity": "simple",
        },
        {
            "question": "Analyze the relationship between response time, NPS, and churn rate. What strategy would you recommend?",
            "expected_complexity": "complex",
        },
    ]

    print("2️⃣  Routing queries to appropriate models...\n")
    print("=" * 80)

    for i, query_data in enumerate(test_queries, 1):
        question = query_data["question"]

        # Classify complexity
        complexity = classify_query_complexity(question)

        # Route to appropriate model
        if complexity == "simple":
            model_name = "gpt-3.5-turbo"
            provider = LLMProvider.OPENAI
            category = "⚡ FAST (Simple lookup)"
        elif complexity == "complex":
            model_name = "claude-opus-4-6"
            provider = LLMProvider.ANTHROPIC
            category = "🧠 POWERFUL (Complex reasoning)"
        else:
            model_name = "gpt-4o"
            provider = LLMProvider.OPENAI
            category = "⚖️  BALANCED (Standard query)"

        print(f"\nQuery {i}: {category}")
        print(f"  Q: {question}")
        print(f"  Model: {model_name} ({provider.value})")
        print(f"  Complexity: {complexity}")

        try:
            engine = await create_engine_with_model(model_name, provider)
            async with engine:
                response = await engine.ask(
                    "business_kb",
                    question=question,
                    top_k=8,
                )
                print(f"  A: {response.answer[:200]}...")
                print(f"  ✓ Responded with appropriate model")
        except ValueError as e:
            print(f"  ⚠️  Skipped: {e}")

    print("\n" + "=" * 80)

    # Cost analysis
    print("\n3️⃣  Cost & Performance Analysis\n")
    print("Model Selection Strategy:")
    print()
    print("┌─ Simple Queries (30% of traffic)")
    print("│  └─ gpt-3.5-turbo  → $0.0005/req, 100ms latency")
    print("│     Perfect for: User lookups, quick facts")
    print()
    print("├─ Standard Queries (50% of traffic)")
    print("│  └─ gpt-4o         → $0.003/req, 300ms latency")
    print("│     Perfect for: Policy questions, recommendations")
    print()
    print("└─ Complex Queries (20% of traffic)")
    print("   └─ claude-opus    → $0.015/req, 800ms latency")
    print("      Perfect for: Deep analysis, diagnosis, strategy")
    print()
    print("Expected Monthly Savings: ~60% compared to using Opus for all queries")
    print()

    # Implementation tips
    print("4️⃣  Implementation Tips for Production\n")
    print("✓ Use ML classifier instead of keyword matching")
    print("✓ Cache responses to avoid redundant queries")
    print("✓ Monitor latency SLAs per model")
    print("✓ Implement fallback (downgrade if primary model overloaded)")
    print("✓ Track cost per query for optimization")
    print("✓ A/B test model selections for your specific workload")
    print()
    print("When to use each model:")
    print("  • gpt-3.5-turbo  → Definite: simple facts, lookups, very fast")
    print("  • gpt-4o         → Definite: standard reasoning, good balance")
    print("  • gpt-4-turbo    → Consider: complex analysis, numerical reasoning")
    print("  • claude-opus    → Consider: creative, multi-step reasoning")
    print()


if __name__ == "__main__":
    print("Setup Instructions:")
    print("  1. Set API keys:")
    print("     export OPENAI_API_KEY=sk-...")
    print("     export ANTHROPIC_API_KEY=sk-ant-...")
    print("\n" + "=" * 80 + "\n")

    try:
        asyncio.run(main())
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

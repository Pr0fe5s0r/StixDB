"""
Core SDK — Agent Tuning
========================
Customize the background agent's behavior.

The memory agent runs every 30 seconds by default.
Tune consolidation, decay, pruning, and tier promotion.

    pip install "stixdb-engine[local-dev]"
    python cookbooks/core-sdk/02_agent_tuning.py
"""

import asyncio
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import (
    StorageConfig,
    StorageMode,
    AgentConfig,
    ReasonerConfig,
    LLMProvider,
)


async def main():
    print("=== Agent Tuning Examples ===\n")

    # Example 1: Fast, aggressive consolidation
    print("1️⃣  FAST AGENT (aggressive consolidation)\n")
    print("   Merges similar nodes aggressively")
    print("   Decays memories quickly")
    print("   Prunes cold data more often\n")

    config_fast = StixDBConfig(
        storage=StorageConfig(mode=StorageMode.KUZU, kuzu_path="./agent_fast"),
        agent=AgentConfig(
            cycle_interval_seconds=10.0,  # run every 10s instead of 30s
            consolidation_similarity_threshold=0.85,  # merge more aggressively (lower = more merges)
            decay_half_life_hours=12.0,  # memories fade in 12h instead of 48h
            prune_importance_threshold=0.15,  # prune at 0.15 instead of 0.05 (more aggressive)
            working_memory_max_nodes=128,  # keep fewer hot nodes
            enable_auto_summarize=True,  # automatically summarize clusters
        ),
        reasoner=ReasonerConfig(provider=LLMProvider.NONE),
    )

    # Example 2: Conservative, preserving consolidation
    print("2️⃣  CONSERVATIVE AGENT (preserves everything)\n")
    print("   Merges only when very similar")
    print("   Decays memories slowly")
    print("   Never prunes\n")

    config_conservative = StixDBConfig(
        storage=StorageConfig(
            mode=StorageMode.KUZU, kuzu_path="./agent_conservative"
        ),
        agent=AgentConfig(
            cycle_interval_seconds=300.0,  # run every 5 minutes
            consolidation_similarity_threshold=0.97,  # only merge when almost identical
            decay_half_life_hours=720.0,  # 30 days! memories fade very slowly
            prune_importance_threshold=0.0,  # never prune
            working_memory_max_nodes=512,  # keep lots of hot nodes
            enable_auto_summarize=False,  # don't auto-summarize
            lineage_safe_mode=True,  # pin source nodes so they aren't lost in merges
        ),
        reasoner=ReasonerConfig(provider=LLMProvider.NONE),
    )

    # Example 3: Balanced (good default)
    print("3️⃣  BALANCED AGENT (default, good for most use cases)\n")
    print("   Moderate consolidation")
    print("   Good memory half-life")
    print("   Reasonable prune threshold\n")

    config_balanced = StixDBConfig(
        storage=StorageConfig(mode=StorageMode.KUZU, kuzu_path="./agent_balanced"),
        agent=AgentConfig(
            cycle_interval_seconds=30.0,
            consolidation_similarity_threshold=0.88,
            decay_half_life_hours=48.0,
            prune_importance_threshold=0.05,
            working_memory_max_nodes=256,
            enable_auto_summarize=True,
        ),
        reasoner=ReasonerConfig(provider=LLMProvider.NONE),
    )

    # Run the balanced config
    async with StixDBEngine(config=config_balanced) as engine:
        print("4️⃣  RUNNING DEMO with balanced config\n")

        # Store some facts
        facts = [
            ("User Alice works in payments", "entity"),
            ("Deadline is June 1st", "fact"),
            ("Alice works on payments", "fact"),  # similar to first one
            ("June 1st is the deadline", "fact"),  # similar to second one
            ("Sprint 1 complete", "event"),
            ("Sprint 1 done", "event"),  # duplicate
        ]

        for content, node_type in facts:
            await engine.store("demo", content, node_type=node_type, importance=0.8)

        print(f"   ✓ Stored {len(facts)} facts\n")

        # Show stats
        stats = await engine.get_collection_stats("demo")
        print(f"Before agent cycle:")
        print(f"   Total nodes: {stats['total_nodes']}")
        print(f"   Nodes by type: {stats['nodes_by_type']}\n")

        # Trigger a manual cycle
        print("   Triggering agent cycle...")
        await engine.trigger_agent_cycle("demo")

        # Show stats again
        stats = await engine.get_collection_stats("demo")
        print(f"\nAfter agent cycle:")
        print(f"   Total nodes: {stats['total_nodes']}")
        print(f"   Nodes by type: {stats['nodes_by_type']}")
        print(f"   (Similar facts should have been merged)\n")

        # Show agent status
        status = await engine.get_agent_status("demo")
        print(f"Agent status:")
        print(f"   Cycles completed: {status['cycles_completed']}")
        print(f"   Last cycle duration: {status['last_cycle_duration_ms']}ms")


if __name__ == "__main__":
    asyncio.run(main())

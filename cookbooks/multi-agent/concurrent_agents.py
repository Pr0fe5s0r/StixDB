"""
Multi-Agent — Concurrent Independent Agents
============================================
Run multiple agents (collections) concurrently, each with its own memory.

Each collection has:
  • Independent graph (nodes/edges)
  • Separate vector search
  • Own background agent cycle
  • Autonomous consolidation & pruning

    pip install "stixdb-engine[local-dev]"
    python cookbooks/multi-agent/concurrent_agents.py
"""

import asyncio
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import StorageConfig, StorageMode, ReasonerConfig, LLMProvider


async def main():
    print("=== Multi-Agent System ===\n")

    # Single engine, multiple collections (agents)
    config = StixDBConfig(
        storage=StorageConfig(mode=StorageMode.KUZU, kuzu_path="./multi_agent_memory"),
        reasoner=ReasonerConfig(provider=LLMProvider.NONE),
    )

    async with StixDBEngine(config=config) as engine:
        # ── Agent 1: Payments Team ────────────────────────────────────────────
        print("1️⃣  Payments Team Agent\n")

        payments_facts = [
            "Alice leads the payments team",
            "Deadline for payment gateway is June 1st",
            "Using Stripe for payment processing",
            "3 engineers on the team",
        ]

        for fact in payments_facts:
            await engine.store(
                "payments_team",
                fact,
                node_type="fact",
                tags=["payments"],
                importance=0.8,
            )

        print("   ✓ Stored payments team knowledge\n")

        # ── Agent 2: DevOps Team ──────────────────────────────────────────────
        print("2️⃣  DevOps Team Agent\n")

        devops_facts = [
            "Bob leads the DevOps team",
            "Infrastructure runs on AWS",
            "Database is PostgreSQL 15",
            "Kubernetes for orchestration",
            "5 engineers on the team",
        ]

        for fact in devops_facts:
            await engine.store(
                "devops_team",
                fact,
                node_type="fact",
                tags=["devops", "infrastructure"],
                importance=0.8,
            )

        print("   ✓ Stored DevOps team knowledge\n")

        # ── Agent 3: Analytics Team ───────────────────────────────────────────
        print("3️⃣  Analytics Team Agent\n")

        analytics_facts = [
            "Carol leads the Analytics team",
            "Using BigQuery for data warehouse",
            "Real-time dashboards with Looker",
            "2 data engineers, 1 analyst",
        ]

        for fact in analytics_facts:
            await engine.store(
                "analytics_team",
                fact,
                node_type="fact",
                tags=["analytics", "data"],
                importance=0.8,
            )

        print("   ✓ Stored Analytics team knowledge\n")

        # ── Concurrent queries ────────────────────────────────────────────────
        print("4️⃣  Concurrent Queries\n")

        queries = [
            ("payments_team", "Who leads payments and what's the deadline?"),
            ("devops_team", "What infrastructure do we use?"),
            ("analytics_team", "What tools do we have for analytics?"),
        ]

        # Run all queries concurrently
        tasks = [
            engine.retrieve(collection, query, top_k=2)
            for collection, query in queries
        ]

        results = await asyncio.gather(*tasks)

        for (collection, query), result in zip(queries, results):
            print(f"\nCollection: {collection}")
            print(f"Q: {query}")
            for res in result:
                print(f"  • [{res['score']:.3f}] {res['content']}")

        # ── Cross-team queries (search across agents) ─────────────────────────
        print("\n5️⃣  Cross-Team Search\n")

        collections = ["payments_team", "devops_team", "analytics_team"]
        cross_query = "Who are the team leads?"

        cross_results = await engine.search(
            query=cross_query,
            collections=collections,
            max_results=5,
        )

        print(f"Q: {cross_query}\n")
        print(f"Results across all teams:\n")
        for result in cross_results:
            col = result.get("collection", "unknown")
            print(f"  • [{result['score']:.3f}] [{col}] {result['content']}")

        # ── Agent stats ───────────────────────────────────────────────────────
        print("\n6️⃣  Agent Statistics\n")

        for collection in collections:
            stats = await engine.get_collection_stats(collection)
            status = await engine.get_agent_status(collection)

            print(f"\n{collection}:")
            print(f"  Nodes: {stats['total_nodes']}")
            print(f"  Cycles: {status['cycles_completed']}")
            print(f"  Status: {status['status']}")

        # ── Concurrent consolidation ──────────────────────────────────────────
        print("\n7️⃣  Trigger All Agent Cycles\n")

        cycle_tasks = [
            engine.trigger_agent_cycle(collection) for collection in collections
        ]
        await asyncio.gather(*cycle_tasks)

        print("   ✓ All agents completed consolidation\n")

        # ── Final stats ───────────────────────────────────────────────────────
        print("8️⃣  Final Statistics\n")

        for collection in collections:
            stats = await engine.get_collection_stats(collection)
            print(f"{collection}: {stats['total_nodes']} nodes, {stats['total_edges']} edges")


if __name__ == "__main__":
    asyncio.run(main())

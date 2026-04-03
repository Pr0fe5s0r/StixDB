"""
Core SDK — Basic Store & Retrieve
==================================
The simplest StixDB example. Store facts, then search them.

No LLM, no Docker, no configuration needed.

    pip install "stixdb-engine[local-dev]"
    python cookbooks/core-sdk/01_basic_store_retrieve.py
"""

import asyncio
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import StorageConfig, StorageMode, ReasonerConfig, LLMProvider


async def main():
    # Configure: persistent local storage, no LLM
    config = StixDBConfig(
        storage=StorageConfig(
            mode=StorageMode.KUZU,
            kuzu_path="./agent_memory",  # data persists here
        ),
        reasoner=ReasonerConfig(provider=LLMProvider.NONE),  # no API key needed
    )

    async with StixDBEngine(config=config) as engine:
        print("=== StixDB: Store & Retrieve ===\n")

        # 1. Store memories (the agent processes these automatically)
        print("📝 Storing memories...")
        await engine.store(
            "my_agent",
            "Alice is the lead engineer on the payments team",
            node_type="entity",
            tags=["team", "contacts"],
            importance=0.9,
        )

        await engine.store(
            "my_agent",
            "Project deadline is June 1st, 2026",
            node_type="fact",
            tags=["deadline", "project"],
            importance=0.85,
        )

        await engine.store(
            "my_agent",
            "Sprint 1 includes payment gateway integration",
            node_type="event",
            tags=["sprint", "payments"],
            importance=0.7,
        )

        await engine.store(
            "my_agent",
            "Use event sourcing pattern for audit trail",
            node_type="concept",
            tags=["architecture", "payments"],
            importance=0.6,
        )

        print("   ✓ Stored 4 memories\n")

        # 2. Search the agent's memory (Search API — no LLM needed)
        print("🔍 Searching memories (no LLM)...\n")

        queries = [
            "Who is responsible for payments?",
            "When is the project deadline?",
            "What architecture pattern are we using?",
        ]

        for query in queries:
            results = await engine.retrieve(
                "my_agent",
                query=query,
                top_k=3,
            )

            print(f"Q: {query}")
            print(f"Results ({len(results)} found):\n")
            for i, result in enumerate(results, 1):
                print(
                    f"  {i}. [{result['score']:.3f}] {result['content']}"
                )
                print(f"     Type: {result['node_type']} | Tier: {result['tier']}\n")

        # 3. Inspect the agent's work
        print("\n📊 Agent Status:\n")
        status = await engine.get_collection_stats("my_agent")
        print(f"Total nodes: {status['total_nodes']}")
        print(f"Total edges: {status['total_edges']}")
        print(f"Nodes by tier: {status['nodes_by_tier']}")
        print(f"Nodes by type: {status['nodes_by_type']}\n")

        # 4. Bulk store
        print("📦 Bulk storing more memories...\n")
        await engine.bulk_store(
            "my_agent",
            items=[
                {
                    "content": "Code review happens every Friday",
                    "node_type": "procedure",
                    "tags": ["process", "review"],
                    "importance": 0.5,
                },
                {
                    "content": "Database is PostgreSQL 15",
                    "node_type": "fact",
                    "tags": ["infrastructure", "database"],
                    "importance": 0.7,
                },
            ],
        )
        print("   ✓ Bulk stored 2 memories\n")

        # 5. Search again (agent has been working in the background)
        print("🔄 Searching again...\n")
        results = await engine.retrieve(
            "my_agent",
            query="infrastructure decisions",
            top_k=2,
        )
        print(f"Q: infrastructure decisions\n")
        for i, result in enumerate(results, 1):
            print(f"  {i}. [{result['score']:.3f}] {result['content']}\n")

        # 6. Get agent status
        print("\n⚙️  Agent Cycle Info:\n")
        agent_status = await engine.get_agent_status("my_agent")
        print(f"Collection: {agent_status['collection']}")
        print(f"Cycles completed: {agent_status['cycles_completed']}")
        print(f"Last cycle duration: {agent_status['last_cycle_duration_ms']}ms")
        print(f"Status: {agent_status['status']}\n")


if __name__ == "__main__":
    asyncio.run(main())

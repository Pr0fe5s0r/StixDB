"""
Core SDK — Local vs Server Mode
================================
Understand when to use local mode (no server) vs server mode.

LOCAL MODE (no server):
  • Direct Python process
  • No HTTP overhead
  • Perfect for agents, scripts, automation
  • `StorageMode.KUZU` with async/await

SERVER MODE (with stixdb serve):
  • HTTP REST API
  • OpenAI-compatible endpoint
  • Share data across services
  • Integration with web apps, LangChain, etc.

Same data. Different access patterns.

    pip install "stixdb-engine[local-dev]"
    python cookbooks/core-sdk/03_local_vs_server.py
"""

import asyncio
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import StorageConfig, StorageMode, ReasonerConfig, LLMProvider


async def example_local_mode():
    """
    LOCAL MODE: No server needed.

    Use this when:
      • Building a Python agent
      • Writing automation scripts
      • Running background tasks
      • Direct access from your code
    """
    print("=" * 70)
    print("1️⃣  LOCAL MODE (No Server)")
    print("=" * 70)
    print()
    print("Use: async with StixDBEngine(config)")
    print("Access: Direct Python methods")
    print("No HTTP, no server startup needed")
    print()

    config = StixDBConfig(
        storage=StorageConfig(
            mode=StorageMode.KUZU,
            kuzu_path="./local_agent_memory",
        ),
        reasoner=ReasonerConfig(provider=LLMProvider.NONE),
    )

    # Start the engine directly in your code
    async with StixDBEngine(config=config) as engine:
        print("✓ Engine started (no server process)\n")

        # Store
        print("Storing memories...")
        await engine.store(
            "my_agent",
            "Alice leads the engineering team",
            node_type="entity",
            importance=0.9,
        )
        await engine.store(
            "my_agent",
            "Deadline is June 1st, 2026",
            node_type="fact",
            importance=0.85,
        )
        print("✓ Stored 2 memories\n")

        # Search
        print("Retrieving...")
        results = await engine.retrieve(
            "my_agent",
            query="Who leads engineering?",
            top_k=3,
        )
        print(f"Found {len(results)} results:")
        for res in results:
            print(f"  • [{res['score']:.3f}] {res['content']}\n")

        # Agent inspection
        print("Checking agent status...")
        status = await engine.get_agent_status("my_agent")
        print(f"Cycles completed: {status['cycles_completed']}\n")

        # All operations are direct, synchronous-looking
        # No network latency, no separate process to manage


async def example_server_mode_setup():
    """
    SERVER MODE SETUP: Start the engine that listens on HTTP.

    Run this to prepare data, then access via HTTP in another script.

    Use this when:
      • Building web apps
      • Using OpenAI SDK
      • LangChain integration
      • Multiple services need access
      • REST API clients
    """
    print("\n" + "=" * 70)
    print("2️⃣  SERVER MODE (with stixdb serve)")
    print("=" * 70)
    print()
    print("Start: stixdb serve --port 4020")
    print("Access: HTTP /v1/chat/completions, /search, /ask")
    print("Client: OpenAI SDK, curl, LangChain, etc.")
    print()

    config = StixDBConfig(
        storage=StorageConfig(
            mode=StorageMode.KUZU,
            kuzu_path="./server_agent_memory",  # same data directory
        ),
        reasoner=ReasonerConfig(provider=LLMProvider.NONE),
    )

    # Same engine, same data
    async with StixDBEngine(config=config) as engine:
        print("✓ Engine ready to serve HTTP requests\n")

        print("Storing test data...")
        facts = [
            "Python is a programming language",
            "Async allows concurrent operations",
            "StixDB stores graph-based memory",
        ]

        for fact in facts:
            await engine.store("knowledge_base", fact, node_type="fact")

        print(f"✓ Stored {len(facts)} facts\n")

        print("Now you would run:")
        print("  $ stixdb serve --port 4020\n")
        print("Then access via HTTP:")
        print("  curl -X POST http://localhost:4020/collections/knowledge_base/retrieve ...")
        print("  curl -X POST http://localhost:4020/v1/chat/completions ...\n")


async def example_transition():
    """
    TRANSITION: Same data, different access.

    Step 1: Store data locally (direct)
    Step 2: Start server (stixdb serve)
    Step 3: Access same data via HTTP
    """
    print("\n" + "=" * 70)
    print("3️⃣  TRANSITION: Local → Server")
    print("=" * 70)
    print()

    shared_path = "./shared_memory"

    # STEP 1: Local mode (store data)
    print("STEP 1: Store data locally\n")

    config = StixDBConfig(
        storage=StorageConfig(mode=StorageMode.KUZU, kuzu_path=shared_path),
        reasoner=ReasonerConfig(provider=LLMProvider.NONE),
    )

    async with StixDBEngine(config=config) as engine:
        await engine.store(
            "project",
            "Backend team working on APIs",
            node_type="fact",
        )
        await engine.store(
            "project",
            "Frontend team working on UI",
            node_type="fact",
        )

        stats = await engine.get_collection_stats("project")
        print(f"✓ Stored memories: {stats['total_nodes']} nodes\n")

    # Data is now persisted to ./shared_memory/kuzu/
    print("Data saved to:", shared_path)
    print()

    # STEP 2: Server mode (same data)
    print("STEP 2: Start server\n")
    print("You would now run:")
    print("  $ stixdb serve --port 4020")
    print()
    print("This starts the HTTP server on the SAME data directory")
    print()

    # STEP 3: Access via HTTP (simulated)
    print("STEP 3: Access via HTTP\n")
    print("From another script or client:")
    print()
    print("  from openai import OpenAI")
    print("  client = OpenAI(")
    print("    base_url='http://localhost:4020/v1',")
    print("    api_key='your-key'")
    print("  )")
    print()
    print("  response = client.chat.completions.create(")
    print("    model='project',")
    print("    messages=[...]")
    print("  )")
    print()

    # Verify data still exists
    async with StixDBEngine(config=config) as engine:
        stats = await engine.get_collection_stats("project")
        print(f"✓ Verified: {stats['total_nodes']} nodes still exist\n")

    print("Same data. Different access method.")


async def example_comparison():
    """
    COMPARISON: When to use each mode.
    """
    print("\n" + "=" * 70)
    print("4️⃣  QUICK COMPARISON")
    print("=" * 70)
    print()

    scenarios = [
        {
            "scenario": "Writing a Python agent that runs locally",
            "mode": "LOCAL",
            "how": "async with StixDBEngine()",
            "server": "❌ No",
        },
        {
            "scenario": "Integrating with LangChain",
            "mode": "SERVER or LOCAL",
            "how": "LOCAL: StixDBRetriever(engine) | SERVER: HTTP client",
            "server": "❌/✅ Optional",
        },
        {
            "scenario": "Using OpenAI SDK (drop-in replacement)",
            "mode": "SERVER",
            "how": "OpenAI(base_url='http://localhost:4020/v1')",
            "server": "✅ Yes (stixdb serve)",
        },
        {
            "scenario": "Building a web API (FastAPI, Flask)",
            "mode": "SERVER",
            "how": "HTTP REST API from web framework",
            "server": "✅ Yes (stixdb serve)",
        },
        {
            "scenario": "Background task / cron job",
            "mode": "LOCAL",
            "how": "async with StixDBEngine()",
            "server": "❌ No",
        },
        {
            "scenario": "Multiple services sharing data",
            "mode": "SERVER",
            "how": "All services call HTTP API",
            "server": "✅ Yes (stixdb serve)",
        },
        {
            "scenario": "Debugging / development",
            "mode": "LOCAL",
            "how": "Direct Python debugging",
            "server": "❌ No",
        },
        {
            "scenario": "Production deployment (Docker)",
            "mode": "SERVER + NEO4J",
            "how": "docker compose up -d",
            "server": "✅ Yes (Docker)",
        },
    ]

    for i, s in enumerate(scenarios, 1):
        print(f"{i}. {s['scenario']}")
        print(f"   Mode: {s['mode']}")
        print(f"   How: {s['how']}")
        print(f"   Server: {s['server']}")
        print()


async def main():
    print("\n" + "🎯 " * 25)
    print("LOCAL vs SERVER MODE IN STIXDB")
    print("🎯 " * 25)
    print()

    await example_local_mode()
    await example_server_mode_setup()
    await example_transition()
    await example_comparison()

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print()
    print("LOCAL (no server):")
    print("  • Use: StorageMode.KUZU")
    print("  • Start: async with StixDBEngine()")
    print("  • Access: Direct Python methods")
    print("  • Best for: Agents, scripts, automation")
    print()
    print("SERVER (stixdb serve):")
    print("  • Use: StorageMode.KUZU (or NEO4J for Docker)")
    print("  • Start: stixdb serve --port 4020")
    print("  • Access: HTTP REST API, OpenAI SDK")
    print("  • Best for: Web apps, integrations, multi-service")
    print()
    print("SAME DATA. Different access method.")
    print()


if __name__ == "__main__":
    asyncio.run(main())

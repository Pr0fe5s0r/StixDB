"""
OpenAI-Compatible — Using the OpenAI SDK
=========================================
Use StixDB with the OpenAI Python SDK by pointing to the local endpoint.

StixDB exposes /v1/chat/completions — same interface as OpenAI.

Prerequisites:
    • StixDB server running: stixdb serve --port 4020
    • export OPENAI_API_KEY=your-key  (or ANTHROPIC_API_KEY, etc.)

    pip install "stixdb-engine[local-dev]" openai
    python cookbooks/openai-compatible/with_openai_sdk.py
"""

from openai import OpenAI, AsyncOpenAI
import os


# ── Standard OpenAI SDK (drop-in replacement) ──────────────────────────────────
def example_sync_chat():
    """Use StixDB with the standard OpenAI SDK."""
    print("=== OpenAI SDK with StixDB ===\n")
    print("1️⃣  Sync chat\n")

    # Point to local StixDB instead of OpenAI
    client = OpenAI(
        base_url="http://localhost:4020/v1",  # StixDB endpoint
        api_key=os.getenv("STIXDB_API_KEY", "test-key"),  # API key if set
    )

    # Use exactly like OpenAI SDK
    response = client.chat.completions.create(
        model="my_agent",  # collection name (not "gpt-4o")
        messages=[
            {
                "role": "user",
                "content": "What are the project deadlines?",
            }
        ],
        temperature=0.2,
        max_tokens=500,
    )

    print(f"Q: What are the project deadlines?\n")
    print(f"A: {response.choices[0].message.content}\n")
    print(f"Tokens used: {response.usage.total_tokens}\n")


# ── Streaming ───────────────────────────────────────────────────────────────────
def example_streaming():
    """Stream responses for real-time output."""
    print("2️⃣  Streaming chat\n")

    client = OpenAI(
        base_url="http://localhost:4020/v1",
        api_key=os.getenv("STIXDB_API_KEY", "test-key"),
    )

    # Set stream=True for streaming responses
    stream = client.chat.completions.create(
        model="my_agent",
        messages=[
            {
                "role": "user",
                "content": "Summarize the current project status in 3 points",
            }
        ],
        stream=True,
    )

    print("Q: Summarize the project status\n")
    print("A: ", end="", flush=True)

    for chunk in stream:
        if chunk.choices[0].delta.content:
            print(chunk.choices[0].delta.content, end="", flush=True)

    print("\n\n")


# ── Multi-turn conversation ───────────────────────────────────────────────────
def example_multi_turn():
    """Maintain conversation history."""
    print("3️⃣  Multi-turn conversation\n")

    client = OpenAI(
        base_url="http://localhost:4020/v1",
        api_key=os.getenv("STIXDB_API_KEY", "test-key"),
    )

    # Build conversation history
    messages = []

    # Turn 1
    messages.append(
        {
            "role": "user",
            "content": "What is the project timeline?",
        }
    )
    response1 = client.chat.completions.create(
        model="my_agent",
        messages=messages,
    )
    answer1 = response1.choices[0].message.content
    messages.append({"role": "assistant", "content": answer1})

    print("Q: What is the project timeline?")
    print(f"A: {answer1}\n")

    # Turn 2 (context is preserved)
    messages.append(
        {
            "role": "user",
            "content": "Who is responsible for that?",
        }
    )
    response2 = client.chat.completions.create(
        model="my_agent",
        messages=messages,
    )
    answer2 = response2.choices[0].message.content

    print("Q: Who is responsible for that?")
    print(f"A: {answer2}\n")


# ── List available models (collections) ──────────────────────────────────────
def example_list_models():
    """List all collections as available models."""
    print("4️⃣  List available models\n")

    client = OpenAI(
        base_url="http://localhost:4020/v1",
        api_key=os.getenv("STIXDB_API_KEY", "test-key"),
    )

    models = client.models.list()
    print("Available collections (models):\n")
    for model in models.data:
        print(f"  • {model.id}")
    print()


# ── Async example ───────────────────────────────────────────────────────────────
async def example_async_chat():
    """Use AsyncOpenAI for concurrent requests."""
    print("5️⃣  Async chat\n")

    client = AsyncOpenAI(
        base_url="http://localhost:4020/v1",
        api_key=os.getenv("STIXDB_API_KEY", "test-key"),
    )

    response = await client.chat.completions.create(
        model="my_agent",
        messages=[
            {
                "role": "user",
                "content": "What are the key risks?",
            }
        ],
    )

    print("Q: What are the key risks?\n")
    print(f"A: {response.choices[0].message.content}\n")


# ── Integration with other libraries ───────────────────────────────────────────
def example_with_langchain():
    """Use StixDB in LangChain via OpenAI interface."""
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        print("⚠️  Requires: pip install langchain-openai")
        return

    print("6️⃣  With LangChain ChatOpenAI\n")

    # LangChain will use StixDB instead of OpenAI
    llm = ChatOpenAI(
        base_url="http://localhost:4020/v1",
        api_key=os.getenv("STIXDB_API_KEY", "test-key"),
        model="my_agent",  # collection name
    )

    response = llm.invoke("Explain the project architecture")
    print(f"Q: Explain the project architecture\n")
    print(f"A: {response.content}\n")


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("StixDB as OpenAI-Compatible Endpoint")
    print("=" * 60)
    print("\nMake sure:")
    print("  1. StixDB server is running: stixdb serve")
    print("  2. API key is set: export STIXDB_API_KEY=your-key")
    print("  3. Memories are stored in 'my_agent' collection")
    print("\n" + "=" * 60 + "\n")

    try:
        example_sync_chat()
        example_streaming()
        example_multi_turn()
        example_list_models()
        example_with_langchain()

        # Run async example
        import asyncio

        asyncio.run(example_async_chat())

    except Exception as e:
        print(f"❌ Error: {e}")
        print("\nMake sure the StixDB server is running:")
        print("  stixdb serve --port 4020")


if __name__ == "__main__":
    main()

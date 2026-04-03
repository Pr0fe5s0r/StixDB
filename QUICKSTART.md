# 🚀 StixDB Quick Start

Build intelligent agent memory on your laptop in 5 minutes. No Docker, no external services required.

---

## 1. Installation

```bash
pip install "stixdb-engine[local-dev]"
```

This installs everything you need: the StixDB engine, a local database (KuzuDB), and a local embedding model.

---

## 2. Your First Memory Agent

Create a file named `my_agent.py` and paste this code. It stores a few facts and then searches them—**without needing any API keys**.

```python
import asyncio
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import StorageConfig, StorageMode, ReasonerConfig, LLMProvider

async def main():
    # 1. Setup - Persistent local storage, no LLM needed for basic search
    config = StixDBConfig(
        storage=StorageConfig(
            mode=StorageMode.KUZU,
            kuzu_path="./my_agent_memory",  # Your data is saved here!
        ),
        reasoner=ReasonerConfig(provider=LLMProvider.NONE),
    )

    async with StixDBEngine(config=config) as engine:
        # 2. Store some memories
        print("Saving memories...")
        await engine.store("my_agent", "Alice is the lead engineer on the payments team.")
        await engine.store("my_agent", "The project deadline is June 1st, 2026.")

        # 3. Search the memory
        print("\nSearching...")
        results = await engine.retrieve("my_agent", query="Who is on the payments team?")
        
        for res in results:
            print(f"-> Found: {res['content']}")

if __name__ == "__main__":
    asyncio.run(main())
```

**Run it:**
```bash
python my_agent.py
```

---

## 3. Add AI Reasoning (Chat with your Data)

To unlock the `ask()` and `chat()` features (where the AI explains its answers), you just need to add an API key.

```python
# Change your config to use OpenAI (or Anthropic/Ollama)
config = StixDBConfig(
    # ... (same storage config as above)
    reasoner=ReasonerConfig(
        provider=LLMProvider.OPENAI,
        model="gpt-4o",
    ),
)

async with StixDBEngine(config=config) as engine:
    # Now the agent can answer complex questions!
    response = await engine.ask("my_agent", "Summarize the project status.")
    print(f"AI Answer: {response.answer}")
    print(f"AI Reasoning: {response.reasoning_trace}")
```

**Set your key in your terminal:**
```bash
export OPENAI_API_KEY=sk-your-key-here
```

---

## 4. Ingesting Documents (PDFs, Markdown, etc.)

StixDB can read entire folders for you.

```python
# Read a single PDF
await engine.ingest_file("my_agent", filepath="./manual.pdf")

# Read an entire folder of documentation
await engine.ingest_folder("my_agent", folderpath="./docs", recursive=True)
```

---

## 🧠 Core Concepts for Beginners

### The Autonomous Librarian
Behind the scenes, StixDB runs a "cycle" every 30 seconds. This is where it:
- **Merges**: Finds similar facts and combines them.
- **Forgets**: Slowly removes old data that you haven't searched for in a long time.
- **Tiers**: Moves important info into "Working Memory" for faster access.

### Collections
Think of a **Collection** as a separate brain for a specific agent. You might have one for `support_agent`, one for `hr_agent`, and one for `personal_notes`.

---

## 🛠️ Next Steps

- **[Cookbooks](cookbooks/)** — Runnable examples for LangChain, OpenAI, and more.
- **[Full README](README.md)** — Comprehensive feature list.
- **[Production Guide](PRODUCTION.md)** — How to use Docker and scale up.

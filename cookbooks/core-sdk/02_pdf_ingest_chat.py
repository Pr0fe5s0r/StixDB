"""
StixDB — PDF Ingestion & Chat
=============================
This example demonstrates how to ingest a PDF file into StixDB
and then have a reasoning-based chat session with its contents.

Usage:
    export OPENAI_API_KEY=sk-...
    python cookbooks/core-sdk/02_pdf_ingest_chat.py path/to/your.pdf
"""

import asyncio
import os
import sys
from pathlib import Path
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import LLMProvider, ReasonerConfig

async def main():
    # 1. Get PDF path from args or use default
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
    else:
        # Just a fallback for documentation purposes
        print("❌ Please provide a PDF file path.")
        print("Usage: python cookbooks/core-sdk/02_pdf_ingest_chat.py <path_to_pdf>")
        return

    if not os.path.exists(pdf_path):
        print(f"❌ File not found: {pdf_path}")
        return

    # 2. Configure StixDB
    # By default, this uses in-memory graph (NetworkX) and OpenAI for reasoning.
    # Ensure OPENAI_API_KEY is set in your environment.
    config = StixDBConfig(
        reasoner=ReasonerConfig(
            provider=LLMProvider.OPENAI,
            model="gpt-4o",
        ),
        verbose=True
    )

    print(f"🚀 Initializing StixDB Engine...")
    async with StixDBEngine(config=config) as engine:
        collection = "pdf_chat_collection"
        
        # 3. Ingest the PDF
        print(f"📄 Ingesting PDF: {pdf_path}...")
        node_ids = await engine.ingest_file(
            collection=collection,
            filepath=pdf_path,
            tags=["pdf", Path(pdf_path).name],
            chunk_size=800,
            chunk_overlap=150
        )
        print(f"✅ Ingested {len(node_ids)} chunks from the PDF.\n")

        # 4. Agentic Chat
        print("💬 Starting Chat (type 'exit' or 'quit' to stop)")
        print("-" * 50)
        
        session_id = "chat_session_001"
        
        while True:
            try:
                question = input("\n👤 You: ")
                if question.lower() in ["exit", "quit"]:
                    break
                
                if not question.strip():
                    continue

                print("\n🤖 Thinking...")
                # The .ask() method uses the internal reasoning agent 
                # to retrieve context, reason, and answer.
                response = await engine.ask(
                    collection=collection,
                    question=question
                )

                print(f"\n🤖 StixDB: {response.answer}")
                
                if response.sources:
                    print(f"\n📚 Sources used: {len(response.sources)} chunks from {Path(pdf_path).name}")
                    for i, src in enumerate(response.sources[:2], 1): # Show first two sources
                        print(f"   [{i}] \"{src.content[:100]}...\"")

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"❌ Error: {e}")

    print("\n👋 Engine stopped. Bye!")

if __name__ == "__main__":
    if "OPENAI_API_KEY" not in os.environ:
        print("⚠️  Warning: OPENAI_API_KEY not found in environment.")
        print("Please set it: export OPENAI_API_KEY=sk-...")
    
    asyncio.run(main())

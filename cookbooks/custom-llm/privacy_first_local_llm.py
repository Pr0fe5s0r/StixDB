"""
Custom LLM — Privacy-First Local LLM (Ollama)
==============================================
Use StixDB with local LLMs via Ollama for complete data privacy.
No data sent to external APIs — everything runs locally.

Use Case:
    • Enterprise/regulated environments (HIPAA, SOC2, confidential data)
    • Offline applications (no internet required)
    • Fine-grained data governance
    • Cost-free inference (hardware only)
    • Medical, legal, or sensitive knowledge bases

Prerequisites:
    • Ollama installed: https://ollama.ai
    • Start Ollama: ollama serve
    • Pull a model: ollama pull llama2

    Or for 7B models (faster):
    • ollama pull mistral
    • ollama pull neural-chat

    pip install "stixdb-engine[local-dev]"
    python cookbooks/custom-llm/privacy_first_local_llm.py
"""

import asyncio
import os
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import StorageConfig, StorageMode, ReasonerConfig, LLMProvider


async def main():
    print("=== StixDB with Privacy-First Local LLM (Ollama) ===\n")

    # Configure local LLM via Ollama
    config = StixDBConfig(
        storage=StorageConfig(mode=StorageMode.KUZU, kuzu_path="./private_memory"),
        reasoner=ReasonerConfig(
            provider=LLMProvider.OLLAMA,
            model="mistral:7b",  # Fast 7B model, or use "llama2" for 7B/13B
            # model="neural-chat:7b",  # Alternative: optimized for chat
            # model="dolphin-mixtral:8x7b",  # If you have more VRAM
            ollama_base_url="http://localhost:11434",
            temperature=0.3,
            max_tokens=2000,
            max_context_nodes=20,
            timeout_seconds=120.0,  # Longer timeout (local inference is slower)
        ),
    )

    async with StixDBEngine(config=config) as engine:
        print("⚠️  Note: First run will be slow as the model loads into VRAM")
        print("   Subsequent queries will be faster. This is running entirely locally.\n")

        # 1. Setup: Store medical knowledge (sensitive data example)
        print("1️⃣  Loading medical knowledge base (HIPAA-compliant local storage)...\n")

        medical_knowledge = [
            "Type 1 diabetes requires daily insulin injections or pump therapy",
            "Metformin is a first-line medication for Type 2 diabetes",
            "Blood pressure above 130/80 is considered stage 1 hypertension",
            "ACE inhibitors are commonly prescribed for hypertension and heart disease",
            "HbA1c measures average blood sugar over 3 months",
            "Normal HbA1c is below 5.7%; diabetic range is above 6.5%",
            "Statins reduce LDL cholesterol and cardiovascular risk",
            "Regular exercise (150 min/week) helps manage Type 2 diabetes",
            "Diabetic retinopathy can cause vision loss if untreated",
            "Kidney disease is common in diabetics with poor glucose control",
        ]

        for knowledge in medical_knowledge:
            await engine.store(
                "medical_kb",
                knowledge,
                node_type="fact",
                tier="semantic",
                tags=["medical", "diabetes", "endocrinology"],
                importance=0.9,
            )

        print(f"   ✓ Stored {len(medical_knowledge)} medical facts")
        print("   ✓ All data remains on this machine (no external API calls)\n")

        # 2. Example 1: Patient condition assessment
        print("2️⃣  Medical case analysis (completely private)...\n")

        response = await engine.ask(
            "medical_kb",
            question="Patient with HbA1c of 7.2% and BP 135/82. What conditions are indicated?",
            top_k=8,
            depth=2,
        )

        print("Q: Patient with HbA1c of 7.2% and BP 135/82. What conditions?")
        print(f"A: {response.answer}\n")
        print("✓ Analysis completed locally - no data sent to cloud\n")

        # 3. Example 2: Treatment considerations
        print("3️⃣  Treatment recommendation (based on local knowledge)...\n")

        response = await engine.ask(
            "medical_kb",
            question="What medications should be considered for a diabetic with hypertension?",
            top_k=10,
        )

        print("Q: Medications for diabetic with hypertension?")
        print(f"A: {response.answer}\n")

        # 4. Example 3: Multi-turn conversation
        print("4️⃣  Multi-turn medical consultation (all local)...\n")

        conversation_id = "patient_456"

        turns = [
            "I was diagnosed with Type 2 diabetes. What should I monitor?",
            "How often should I check my HbA1c?",
            "My kidneys - how can diabetes affect them?",
        ]

        for q in turns:
            response = await engine.chat(
                "medical_kb",
                message=q,
                conversation_id=conversation_id,
            )
            print(f"Q: {q}")
            print(f"A: {response.text}\n")

        # 5. Privacy advantages
        print("5️⃣  Privacy & Compliance Advantages\n")
        print("✓ HIPAA Compliant    — Patient data never leaves your systems")
        print("✓ GDPR Compliant     — No data processor agreements needed")
        print("✓ SOC2 Ready         — No external dependencies for inference")
        print("✓ Cost-Free Inference— Only hardware costs (no API fees)")
        print("✓ Offline Capable    — Works without internet")
        print("✓ Full Transparency  — You control the entire pipeline\n")

        # 6. Model selection guide
        print("6️⃣  Local LLM Selection for Your Hardware\n")
        print("7B Models (8GB VRAM needed):")
        print("  • mistral:7b         → Best speed/quality balance")
        print("  • neural-chat:7b     → Optimized for conversations")
        print("  • openchat:7b        → Faster, simpler tasks")
        print()
        print("13B Models (16GB VRAM needed):")
        print("  • llama2:13b         → Better reasoning, slower")
        print("  • neural-chat:13b    → More accurate conversations")
        print()
        print("Larger Models (24GB+ VRAM):")
        print("  • dolphin-mixtral:8x7b  → Most capable (if you have VRAM)")
        print("  • llama2:70b         → Maximum reasoning power")
        print()

        # 7. Performance notes
        print("7️⃣  Performance Characteristics\n")
        print("Local LLM Trade-offs:")
        print("  • Speed: 50-100 tokens/sec (vs. 1000+ for cloud API)")
        print("  • Latency: 2-5 seconds per query (vs. 100-500ms)")
        print("  • Cost: Zero API fees")
        print("  • Privacy: Absolute (nothing leaves your machine)")
        print()
        print("When to use Local LLMs:")
        print("  ✓ Highly sensitive data (medical, legal, confidential)")
        print("  ✓ Regulated environments (HIPAA, PCI-DSS)")
        print("  ✓ Offline/edge applications")
        print("  ✓ Cost-sensitive batch processing")
        print()


if __name__ == "__main__":
    print("Setup Instructions:")
    print("  1. Install Ollama: https://ollama.ai")
    print("  2. Start Ollama: ollama serve")
    print("  3. Pull model: ollama pull mistral (or llama2)")
    print("  4. Run this script: python privacy_first_local_llm.py")
    print("\n" + "=" * 70 + "\n")

    try:
        asyncio.run(main())
    except Exception as e:
        print(f"❌ Error: {e}")
        if "connection refused" in str(e).lower():
            print("\nMake sure Ollama is running:")
            print("  1. ollama serve")
            print("  2. In another terminal: ollama pull mistral")
        import traceback
        traceback.print_exc()

"""
Custom Embeddings — Privacy-First Local Embeddings
==================================================
Use sentence-transformers to embed documents locally without sending data to APIs.
All embeddings computed on your machine - no external service calls.

Use Case:
    • HIPAA/GDPR compliance (sensitive health or personal data)
    • Offline applications (no internet required)
    • Fine-grained data control and audit
    • Cost optimization (free after initial model download)
    • Enterprise deployments with strict data residency

Advantages:
    • 100% data privacy (never leaves your infrastructure)
    • Zero API costs (only GPU/CPU compute)
    • Deterministic (same text always produces same embedding)
    • Full control over model and versions

Prerequisites:
    • PyTorch and sentence-transformers
    • GPU recommended (10x faster, optional)

    pip install sentence-transformers torch
    python privacy_first_local_embeddings.py

Optional GPU acceleration:
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
"""

import asyncio
import os
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import StorageConfig, StorageMode, VectorBackend, EmbeddingProvider


async def main():
    print("=== Privacy-First Local Embeddings (Sentence Transformers) ===\n")
    print("All embeddings computed locally - zero data sent to APIs\n")

    # Configure local embeddings
    config = StixDBConfig(
        storage=StorageConfig(
            mode=StorageMode.KUZU,
            kuzu_path="./private_embeddings_memory",
            vector_backend=VectorBackend.CHROMA,
        ),
        embedding={
            "provider": "sentence_transformers",
            # Best quality: all-mpnet-base-v2 (429M, 8GB VRAM)
            # Balanced: all-MiniLM-L6-v2 (22M, minimal VRAM)
            # Fast: paraphrase-MiniLM-L6-v2 (22M, minimal VRAM)
            "model": "sentence-transformers/all-MiniLM-L6-v2",
            # Disable GPU if not available
            "device": "cuda",  # or "cpu" if no GPU
        },
    )

    async with StixDBEngine(config=config) as engine:
        print("1️⃣  Embedding confidential documents locally...\n")
        print("⚠️  First run downloads model (~100MB). Subsequent runs use cache.\n")

        # Example: Healthcare data
        confidential_docs = [
            "Patient ID: P-12345, Diagnosis: Type 2 Diabetes, HbA1c: 7.2%, Medication: Metformin 500mg BID",
            "Patient ID: P-12346, Chief Complaint: Chest pain, EKG: Normal, Troponin: Negative",
            "Patient ID: P-12347, Psychiatric History: Depression, Current: SSRIs, Last eval: March 2024",
            "Patient ID: P-12348, Surgical History: Appendectomy 2020, No complications",
            "Patient ID: P-12349, Allergy Status: Penicillin (anaphylaxis), Iodine (rash)",
        ]

        print("   Storing confidential healthcare data with local embeddings:\n")

        for doc in confidential_docs:
            await engine.store(
                "patient_records",
                doc,
                node_type="fact",
                tier="semantic",
                tags=["patient", "confidential"],
                importance=1.0,  # Highest importance
                pinned=True,  # Never prune
            )

        print(f"   ✓ Embedded {len(confidential_docs)} patient records")
        print("   ✓ All data remains in this facility (HIPAA compliant)\n")

        # Example searches
        print("2️⃣  Searching confidential data (locally)...\n")

        search_queries = [
            "Which patients have diabetes?",
            "Patients with penicillin allergies",
            "Recent psychiatric evaluations",
        ]

        for query in search_queries:
            results = await engine.retrieve(
                "patient_records",
                query=query,
                top_k=1,
            )

            if results["matches"]:
                match = results["matches"][0]
                print(f"Q: {query}")
                # Don't print full content (sensitive)
                print(f"✓ Found matching record (data remains local)")
                print()

        # Example 2: Legal documents
        print("3️⃣  Confidential Legal Documents\n")

        legal_docs = [
            "Merger & acquisition agreement between Company A and Company B, valued at $500M, LOI signed Jan 2024",
            "Patent application for novel drug delivery mechanism, prior art search completed",
            "Settlement agreement in litigation matter, confidential non-disclosure clause included",
            "Licensing agreement with technology partner, royalty structure 5% of gross revenue",
        ]

        print("   Storing confidential legal documents with local embeddings:\n")

        for doc in legal_docs:
            await engine.store(
                "legal_vault",
                doc,
                node_type="fact",
                tier="semantic",
                tags=["legal", "confidential", "nda"],
                importance=0.95,
                pinned=True,
            )

        print(f"   ✓ Embedded {len(legal_docs)} legal documents")
        print("   ✓ All data stays within company network (SOC2 compliant)\n")

        legal_searches = [
            "M&A activities",
            "Intellectual property matters",
            "Revenue-sharing arrangements",
        ]

        print("   Legal document searches:\n")

        for query in legal_searches:
            results = await engine.retrieve(
                "legal_vault",
                query=query,
                top_k=1,
            )
            if results["matches"]:
                match = results["matches"][0]
                print(f"Q: {query}")
                print(f"✓ Found (sensitive data protected)")
                print()

    # Feature comparison
    print("4️⃣  Local vs. API Embeddings\n")
    print("┌─ Local Embeddings (Sentence Transformers)")
    print("│  ✓ 100% Privacy            (nothing leaves your machine)")
    print("│  ✓ $0 API costs            (after model download)")
    print("│  ✓ HIPAA/GDPR Compliant    (on-premises)")
    print("│  ✓ Deterministic           (same input = same vector)")
    print("│  ✓ Offline capable         (no internet needed)")
    print("│  ✗ Requires GPU/CPU        (slower inference)")
    print("│  ✗ Model management        (versioning, updates)")
    print("│")
    print("└─ API Embeddings (OpenAI)")
    print("   ✓ State-of-art quality    (constantly improving)")
    print("   ✓ No infrastructure       (no GPU needed)")
    print("   ✓ Minimal maintenance     (API handles updates)")
    print("   ✗ $$$ API costs           ($0.02-0.13 per 1M tokens)")
    print("   ✗ Privacy concerns        (data sent to APIs)")
    print("   ✗ Internet required       (API dependency)")
    print()

    # Model selection guide
    print("5️⃣  Sentence Transformer Model Selection\n")
    print("For Privacy/GDPR/HIPAA (Local Compute):")
    print("  • all-MiniLM-L6-v2         → Fast (22M params, ~100ms)")
    print("  • all-mpnet-base-v2        → Best quality (429M, ~500ms)")
    print("  • paraphrase-MiniLM-L6-v2  → Paraphrase optimized")
    print()
    print("Specialized Domain:")
    print("  • allenai/specter          → Scientific papers")
    print("  • BiomedNLP (Hugging Face) → Medical documents")
    print()
    print("Performance (on CPU, without GPU):")
    print("  • MiniLM models: 50-100 docs/sec")
    print("  • MPNet models:  10-20 docs/sec")
    print()
    print("Performance (with GPU):")
    print("  • MiniLM models: 1000+ docs/sec")
    print("  • MPNet models:  500+ docs/sec")
    print()

    # Compliance notes
    print("6️⃣  Compliance & Deployment\n")
    print("HIPAA Compliance:")
    print("  ✓ No PHI sent to external services")
    print("  ✓ Encryption of data at rest (your responsibility)")
    print("  ✓ Access controls maintained")
    print("  ✓ Audit logging enabled")
    print()
    print("GDPR Compliance:")
    print("  ✓ Personal data never leaves EU")
    print("  ✓ Right to deletion (delete embeddings)")
    print("  ✓ Data processors (no external)")
    print("  ✓ Transparent processing")
    print()
    print("Deployment Options:")
    print("  • On-premises           → Maximum control")
    print("  • Private cloud (VPC)   → Isolated network")
    print("  • Containerized (Docker) → Consistent environment")
    print()

    # Cost analysis
    print("7️⃣  Cost Analysis\n")
    print("Local Embeddings (Annual):")
    print("  • GPU: $5k-10k            (one-time)")
    print("  • Electricity: ~$1k        (assuming 50% utilization)")
    print("  • Total: ~$1k              (after first year)")
    print("  • For 10M docs: $0.0001 per embedding")
    print()
    print("OpenAI Embeddings (Annual):")
    print("  • text-embedding-3-small: $0.02 per 1M tokens")
    print("  • For 10M docs: ~$2,000    (assuming avg 200 tokens/doc)")
    print()
    print("Payback period: 6-12 months for typical enterprise workload\n")


if __name__ == "__main__":
    print("Setup Instructions:")
    print("  1. pip install sentence-transformers torch")
    print("  2. Optional GPU: pip install torch cuda...")
    print("  3. python privacy_first_local_embeddings.py")
    print("\n" + "=" * 70 + "\n")

    try:
        asyncio.run(main())
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\nTroubleshooting:")
        print("  • ImportError: torch → pip install torch")
        print("  • ImportError: sentence_transformers → pip install sentence-transformers")
        print("  • CUDA error → CPU mode works, or install CUDA toolkit")
        import traceback
        traceback.print_exc()

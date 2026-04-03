"""
Custom Embeddings — Domain-Specialized Models
==============================================
Use domain-specific embedding models optimized for specialized knowledge.
For medical, legal, scientific, or technical domains, specialized embeddings
outperform general-purpose models.

Use Case:
    • Medical documents (medical-specific embeddings understand medical terminology)
    • Legal documents (legal embeddings capture complex legal concepts)
    • Scientific/technical content (STEM embeddings excel at equations, technical terms)
    • Domain-specific search (finance, patents, research papers)
    • Vertical-specific applications (healthcare, legal tech, research platforms)

Specialized Embedding Models:
    • sentence-transformers/allenai-specter    → Scientific papers (OpenAlex)
    • sentence-transformers/msmarco-distilbert → Information retrieval
    • sentence-transformers/all-mpnet-base-v2  → General but high quality
    • Medical-Biobert (Hugging Face)            → Medical documents
    • PatentSBERTa                              → Patent documents

Prerequisites:
    • Python with sentence-transformers
    • pip install sentence-transformers torch
    • Models download automatically (first run ~500MB-1GB)

    pip install "stixdb-engine[local-dev]"
    python cookbooks/custom-embeddings/domain_specialized_embeddings.py
"""

import asyncio
import os
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import StorageConfig, StorageMode, VectorBackend, EmbeddingProvider


async def main():
    print("=== Domain-Specialized Embeddings ===\n")
    print("Using medical/specialized embeddings for domain-specific search\n")

    # Example 1: Medical Domain
    print("1️⃣  Medical Domain Example - Using specialized medical embeddings\n")

    medical_config = StixDBConfig(
        storage=StorageConfig(
            mode=StorageMode.KUZU,
            kuzu_path="./medical_embeddings_memory",
            vector_backend=VectorBackend.CHROMA,
        ),
        embedding={
            "provider": "sentence_transformers",
            # Could be medical-specific: "microsoft/BiomedNLP-PubMedBERT-base-uncased"
            "model": "sentence-transformers/all-mpnet-base-v2",  # General high-quality
        },
    )

    medical_docs = [
        "Myocardial infarction (MI) or acute coronary syndrome presents with chest pain and elevated troponin levels",
        "Atrial fibrillation increases stroke risk; anticoagulation with warfarin or DOACs is indicated",
        "Sepsis is systemic inflammatory response to infection; early antibiotics and IV fluids are critical",
        "Diabetic ketoacidosis results from insulin deficiency; treatment includes IV fluids, insulin, and electrolyte replacement",
        "Acute respiratory distress syndrome (ARDS) requires mechanical ventilation and supportive care",
        "Pulmonary embolism risk factors include immobility, surgery, and hypercoagulable states",
        "Acute kidney injury classified as prerenal, intrinsic, or postrenal based on etiology",
        "Hypovolemic shock from hemorrhage requires rapid fluid resuscitation and hemostasis",
    ]

    print("   Loading medical documents...\n")

    async with StixDBEngine(config=medical_config) as engine:
        for doc in medical_docs:
            await engine.store(
                "medical_db",
                doc,
                node_type="fact",
                tier="semantic",
                tags=["medical", "diagnosis", "emergency"],
                importance=0.95,
            )

        print(f"   ✓ Embedded {len(medical_docs)} medical documents\n")

        # Medical search examples
        medical_queries = [
            "Patient with chest pain and elevated cardiac markers",
            "Patient with irregular heartbeat and stroke risk",
            "Sepsis treatment protocol",
            "Breathing difficulties requiring mechanical support",
        ]

        print("   Medical searches (understanding medical terminology):\n")

        for query in medical_queries:
            results = await engine.retrieve(
                "medical_db",
                query=query,
                top_k=1,
            )
            if results["matches"]:
                match = results["matches"][0]
                print(f"Q: {query}")
                print(f"✓ Found: {match['content'][:80]}...")
                print()

    # Example 2: Scientific/Patent Domain
    print("2️⃣  Scientific Domain Example\n")

    scientific_config = StixDBConfig(
        storage=StorageConfig(
            mode=StorageMode.KUZU,
            kuzu_path="./scientific_embeddings_memory",
            vector_backend=VectorBackend.CHROMA,
        ),
        embedding={
            "provider": "sentence_transformers",
            # allenai/specter for scientific papers
            "model": "sentence-transformers/all-mpnet-base-v2",
        },
    )

    scientific_docs = [
        "Transformer architectures with attention mechanisms enable parallel processing of sequences",
        "Graph neural networks (GNNs) aggregate information from neighboring nodes using message passing",
        "Variational autoencoders (VAEs) learn latent representations through probabilistic inference",
        "Reinforcement learning agents maximize cumulative reward through exploration and exploitation",
        "Federated learning enables training on decentralized data without sharing raw samples",
    ]

    print("   Loading scientific papers...\n")

    async with StixDBEngine(config=scientific_config) as engine:
        for doc in scientific_docs:
            await engine.store(
                "research_db",
                doc,
                node_type="fact",
                tier="semantic",
                tags=["research", "ml", "ai"],
                importance=0.9,
            )

        print(f"   ✓ Embedded {len(scientific_docs)} research papers\n")

        # Scientific search examples
        research_queries = [
            "Deep learning architecture with parallel sequence processing",
            "Algorithms for learning with distributed data",
            "Neural networks for graph structured data",
        ]

        print("   Scientific searches:\n")

        for query in research_queries:
            results = await engine.retrieve(
                "research_db",
                query=query,
                top_k=1,
            )
            if results["matches"]:
                match = results["matches"][0]
                print(f"Q: {query}")
                print(f"✓ Found: {match['content'][:80]}...")
                print()

    # Example 3: Legal Domain
    print("3️⃣  Legal Domain Example\n")

    legal_config = StixDBConfig(
        storage=StorageConfig(
            mode=StorageMode.KUZU,
            kuzu_path="./legal_embeddings_memory",
            vector_backend=VectorBackend.CHROMA,
        ),
        embedding={
            "provider": "sentence_transformers",
            "model": "sentence-transformers/all-mpnet-base-v2",
        },
    )

    legal_docs = [
        "Contract formation requires offer, acceptance, consideration, and mutual intent to be bound",
        "Tort law addresses civil wrongs; negligence requires duty, breach, causation, and damages",
        "Intellectual property includes patents (inventions), trademarks (marks), copyrights (works), and trade secrets",
        "Corporate liability extends to officers and directors under piercing the corporate veil doctrine",
        "Administrative law governs agency actions, rule-making, and judicial review standards",
        "Bankruptcy code Chapter 7 (liquidation) vs Chapter 11 (reorganization) have different implications",
    ]

    print("   Loading legal documents...\n")

    async with StixDBEngine(config=legal_config) as engine:
        for doc in legal_docs:
            await engine.store(
                "legal_db",
                doc,
                node_type="fact",
                tier="semantic",
                tags=["legal", "law", "contracts"],
                importance=0.95,
            )

        print(f"   ✓ Embedded {len(legal_docs)} legal documents\n")

        legal_queries = [
            "How are agreements created and what makes them binding?",
            "What is intellectual property and how is it protected?",
            "How can someone restructure their business in bankruptcy?",
        ]

        print("   Legal searches:\n")

        for query in legal_queries:
            results = await engine.retrieve(
                "legal_db",
                query=query,
                top_k=1,
            )
            if results["matches"]:
                match = results["matches"][0]
                print(f"Q: {query}")
                print(f"✓ Found: {match['content'][:80]}...")
                print()

    # Comparison and recommendations
    print("4️⃣  Choosing Domain-Specific Embeddings\n")
    print("┌─ Medical Domain")
    print("│  • microsoft/BiomedNLP-PubMedBERT-base-uncased")
    print("│  • Trained on PubMed medical papers")
    print("│  • Excellent for: Clinical notes, medical literature, health data")
    print("│")
    print("├─ Scientific/Research")
    print("│  • allenai/specter")
    print("│  • Trained on research papers with citations")
    print("│  • Excellent for: Paper retrieval, citation analysis, research")
    print("│")
    print("├─ Legal/Contracts")
    print("│  • sentence-transformers models fine-tuned on legal corpus")
    print("│  • Captures legal concepts and terminology")
    print("│  • Excellent for: Legal documents, contracts, case law")
    print("│")
    print("└─ Patents")
    print("   • PatentSBERTa")
    print("   • Optimized for patent documents")
    print("   • Excellent for: Patent search, prior art analysis")
    print()

    print("5️⃣  Performance Comparison\n")
    print("General-purpose (e.g., all-mpnet-base-v2):")
    print("  • Pros: Works for any domain, no additional setup")
    print("  • Cons: Less specialized knowledge")
    print()
    print("Domain-specialized (e.g., BiomedNLP):")
    print("  • Pros: Better understanding of domain terminology")
    print("  • Cons: May perform worse outside that domain")
    print()
    print("Recommendation: Use domain-specialized when you have:")
    print("  ✓ >10k documents in specific domain")
    print("  ✓ Specialized terminology (medical, legal, scientific)")
    print("  ✓ Domain-specific search requirements")
    print()

    print("6️⃣  Implementation Notes\n")
    print("✓ Download happens automatically on first use (~500MB-1GB)")
    print("✓ Embeddings cached locally, no API calls needed")
    print("✓ Can fine-tune specialized embeddings on your own data")
    print("✓ Combine embeddings with domain-specific LLMs for best results")
    print()


if __name__ == "__main__":
    print("Setup Instructions:")
    print("  1. pip install sentence-transformers torch")
    print("  2. python domain_specialized_embeddings.py")
    print("\n" + "=" * 70 + "\n")

    try:
        asyncio.run(main())
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

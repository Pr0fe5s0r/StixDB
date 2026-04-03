"""
LangChain Integration — Full RAG Pipeline
==========================================
Load documents with LangChain, store in StixDB, retrieve and generate.

Pattern:
  1. Load documents (WebBaseLoader, PyPDFLoader, etc.)
  2. Split with RecursiveCharacterTextSplitter
  3. Ingest into StixDB
  4. Retrieve with StixDB
  5. Generate answer with LLM

    pip install langchain langchain-community langchain-text-splitters langchain-openai
    python cookbooks/langchain/rag_pipeline.py
"""

import asyncio
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import StorageConfig, StorageMode, ReasonerConfig, LLMProvider


async def main():
    print("=== LangChain RAG Pipeline ===\n")

    # Step 1: Load documents
    # In production, use real loaders:
    #   from langchain_community.document_loaders import WebBaseLoader, PyPDFLoader
    #   loader = WebBaseLoader("https://example.com")
    #   documents = loader.load()

    print("1️⃣  Loading documents...\n")
    documents = [
        Document(
            page_content=(
                "Transformers use multi-head self-attention to attend to different "
                "parts of the input sequence in parallel."
            ),
            metadata={"source": "arxiv", "year": 2017, "title": "Attention is All You Need"},
        ),
        Document(
            page_content=(
                "BERT uses bidirectional transformers to pre-train on masked language "
                "modeling and next sentence prediction tasks."
            ),
            metadata={"source": "arxiv", "year": 2018, "title": "BERT Paper"},
        ),
        Document(
            page_content=(
                "GPT models use autoregressive decoding, where each token is generated "
                "sequentially based on previous tokens."
            ),
            metadata={"source": "arxiv", "year": 2018, "title": "Language Models are Unsupervised Multitask Learners"},
        ),
        Document(
            page_content=(
                "Vision Transformers (ViT) apply the transformer architecture to image "
                "classification by treating image patches as tokens."
            ),
            metadata={"source": "arxiv", "year": 2020, "title": "An Image is Worth 16x16 Words"},
        ),
    ]

    print(f"   ✓ Loaded {len(documents)} documents\n")

    # Step 2: Split documents into chunks
    print("2️⃣  Splitting documents...\n")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=200,
        chunk_overlap=30,
        length_function=len,
        separators=["\n\n", "\n", " ", ""],
    )
    chunks = splitter.split_documents(documents)
    print(f"   ✓ Created {len(chunks)} chunks\n")

    # Step 3: Configure StixDB
    config = StixDBConfig(
        storage=StorageConfig(mode=StorageMode.KUZU, kuzu_path="./rag_memory"),
        reasoner=ReasonerConfig(
            provider=LLMProvider.OPENAI,
            model="gpt-4o",
            # Set OPENAI_API_KEY env var
        ),
    )

    async with StixDBEngine(config=config) as engine:
        # Step 4: Ingest chunks into StixDB
        print("3️⃣  Ingesting into StixDB...\n")
        ids = await engine.ingest_file(
            "transformer_kb",
            filepath=chunks,  # Pass LangChain documents directly
            source_name="arxiv_papers",
            tags=["transformers", "deep-learning", "nlp"],
            chunk_size=None,  # Don't re-chunk
        )
        print(f"   ✓ Ingested {len(ids)} chunks\n")

        # Step 5: Retrieve (Search API — no LLM cost)
        print("4️⃣  Retrieving relevant documents...\n")
        query = "How do transformers work?"
        results = await engine.retrieve(
            "transformer_kb",
            query=query,
            top_k=3,
            threshold=0.2,
        )

        print(f"Q: {query}\n")
        print(f"Retrieved {len(results)} results:\n")
        for i, result in enumerate(results, 1):
            print(f"  {i}. [{result['score']:.3f}] {result['content']}")
            if result.get('metadata'):
                meta = result['metadata']
                if isinstance(meta, dict):
                    print(f"     Source: {meta.get('source', 'unknown')}")
            print()

        # Step 5: Generate answer using agentic reasoning over retrieved context
        print("5️⃣  Generating answer with LLM reasoning...\n")
        response = await engine.ask(
            "transformer_kb",
            question="Explain the key innovation of transformers in NLP",
            top_k=5,
            depth=2,
        )

        print(f"Answer: {response.answer}\n")
        print(f"Confidence: {response.confidence:.2f}\n")
        print("Sources:")
        for source in response.sources:
            print(f"  • {source.content}")
            print(f"    (score: {source.score:.3f})\n")

        # Step 7: Multi-turn conversation
        print("6️⃣  Multi-turn conversation...\n")
        session_id = "user_123"

        q1 = "What is BERT?"
        response1 = await engine.chat(
            "transformer_kb",
            message=q1,
            session_id=session_id,
        )
        print(f"Q: {q1}")
        print(f"A: {response1.answer}\n")

        q2 = "How does it differ from GPT?"
        response2 = await engine.chat(
            "transformer_kb",
            message=q2,
            session_id=session_id,
        )
        print(f"Q: {q2}")
        print(f"A: {response2.answer}\n")

        # Step 8: Inspect the knowledge base
        print("7️⃣  Knowledge base stats...\n")
        stats = await engine.get_collection_stats("transformer_kb")
        print(f"Total nodes: {stats['total_nodes']}")
        print(f"Total edges: {stats['total_edges']}")
        print(f"Nodes by tier: {stats['nodes_by_tier']}")


if __name__ == "__main__":
    asyncio.run(main())

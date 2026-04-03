"""
LangChain Integration — StixDB as a Retriever
==============================================
Use StixDB as a drop-in LangChain retriever for RAG chains.

This lets you use StixDB in any LangChain chain that expects a retriever.

    pip install langchain langchain-community langchain-openai
    python cookbooks/langchain/stixdb_retriever.py
"""

import asyncio
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.callbacks.manager import CallbackManagerForRetrieverRun
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import StorageConfig, StorageMode, ReasonerConfig, LLMProvider


# ── StixDB Retriever ──────────────────────────────────────────────────────────
class StixDBRetriever(BaseRetriever):
    """
    LangChain retriever wrapping StixDB.

    Drop-in replacement for any LangChain retriever in RAG chains.
    """

    engine: StixDBEngine
    collection: str
    top_k: int = 5
    threshold: float = 0.2
    depth: int = 1

    class Config:
        arbitrary_types_allowed = True

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun | None = None,
    ) -> list[Document]:
        """Synchronous retrieval (required by LangChain BaseRetriever)."""
        import asyncio

        # Get or create event loop
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # Retrieve from StixDB
        results = loop.run_until_complete(
            self.engine.retrieve(
                collection=self.collection,
                query=query,
                top_k=self.top_k,
                threshold=self.threshold,
                depth=self.depth,
            )
        )

        # Convert to LangChain Documents
        return [
            Document(
                page_content=r["content"],
                metadata={
                    **r.get("metadata", {}),
                    "score": r["score"],
                    "node_type": r.get("node_type"),
                    "tier": r.get("tier"),
                },
            )
            for r in results
        ]


# ── Example: Use in a simple chain ───────────────────────────────────────────
async def example_simple_retrieval():
    """Basic usage: retrieve documents."""
    config = StixDBConfig(
        storage=StorageConfig(mode=StorageMode.KUZU, kuzu_path="./retriever_demo"),
    )

    async with StixDBEngine(config=config) as engine:
        # Ingest some facts
        facts = [
            "The Earth orbits the Sun at ~150 million km",
            "Light year is the distance light travels in one year",
            "Mars is the fourth planet from the Sun",
            "Venus is the hottest planet in our solar system",
        ]

        for fact in facts:
            await engine.store(
                "astronomy",
                fact,
                node_type="fact",
                tags=["astronomy", "space"],
                importance=0.8,
            )

        # Create retriever
        retriever = StixDBRetriever(
            engine=engine,
            collection="astronomy",
            top_k=2,
            threshold=0.2,
        )

        # Use the retriever (synchronous)
        print("=== StixDB as LangChain Retriever ===\n")
        print("1️⃣  Simple retrieval\n")

        docs = retriever.invoke("How far is Earth from the Sun?")
        print(f"Q: How far is Earth from the Sun?\n")
        print(f"Retrieved {len(docs)} documents:\n")
        for doc in docs:
            score = doc.metadata.get("score", 0)
            print(f"  • [{score:.3f}] {doc.page_content}")
            print()


# ── Example: Use in a LangChain chain ──────────────────────────────────────────
async def example_with_chain():
    """Advanced: use in a LangChain chain with LLM."""
    try:
        from langchain_openai import ChatOpenAI
        from langchain.chains import create_retrieval_chain
        from langchain.chains.combine_documents import create_stuff_documents_chain
        from langchain_core.prompts import ChatPromptTemplate
    except ImportError:
        print("⚠️  Requires: pip install langchain-openai")
        return

    config = StixDBConfig(
        storage=StorageConfig(mode=StorageMode.KUZU, kuzu_path="./chain_demo"),
        reasoner=ReasonerConfig(provider=LLMProvider.OPENAI, model="gpt-4o"),
    )

    async with StixDBEngine(config=config) as engine:
        # Ingest knowledge base
        docs = [
            "Python is a high-level programming language",
            "NumPy is for numerical computing in Python",
            "Pandas is for data analysis in Python",
            "PyTorch is for machine learning in Python",
        ]

        for doc in docs:
            await engine.store("python_kb", doc, node_type="fact")

        # Create retriever + chain
        retriever = StixDBRetriever(engine=engine, collection="python_kb", top_k=3)

        print("2️⃣  Retriever in a LangChain chain\n")

        # Define chain
        llm = ChatOpenAI(model="gpt-4o", temperature=0.2)

        prompt = ChatPromptTemplate.from_template(
            """Answer the question based on the context:

Context:
{context}

Question: {input}

Answer:"""
        )

        chain = create_retrieval_chain(
            retriever,
            create_stuff_documents_chain(llm, prompt),
        )

        # Run chain
        result = chain.invoke({"input": "What Python libraries are available?"})
        print(f"Q: What Python libraries are available?\n")
        print(f"A: {result['answer']}\n")


# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    await example_simple_retrieval()
    print("\n" + "=" * 50 + "\n")
    await example_with_chain()


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""
Legacy RAG script — embed a folder of documents and query them.
Uses LangChain + ChromaDB (local, persistent).

Usage:
  python scripts/rag.py embed <folder>          # Embed all docs in folder
  python scripts/rag.py query "<question>"      # Query embedded docs
  python scripts/rag.py query "<question>" -k 5 # Return top-5 chunks
  python scripts/rag.py clear                   # Wipe the ChromaDB store

Dependencies:
  pip install langchain langchain-community langchain-openai chromadb openai tiktoken
  (set OPENAI_API_KEY in env, or swap in any other LangChain LLM/embeddings)
"""

import argparse
import os
import sys
from pathlib import Path

# ── LangChain imports ─────────────────────────────────────────────────────────
from langchain_community.document_loaders import (
    DirectoryLoader,
    TextLoader,
    PyPDFLoader,
    UnstructuredMarkdownLoader,
)
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate

# ── Config ────────────────────────────────────────────────────────────────────
CHROMA_DIR = Path(__file__).parent / ".chroma_store"
COLLECTION  = "rag_docs"
CHUNK_SIZE  = 1000
CHUNK_OVERLAP = 150
DEFAULT_K   = 4

EMBED_MODEL = "Qwen/Qwen3-Embedding-8B"   # cheap + fast
LLM_MODEL   = "openai/gpt-oss-120b"             # swap to gpt-4o for better answers

PROMPT_TEMPLATE = """Use the following context to answer the question.
If the answer is not in the context, say "I don't know."

Context:
{context}

Question: {question}

Answer:"""

# ── Loaders by extension ──────────────────────────────────────────────────────
LOADER_MAP = {
    ".pdf": (PyPDFLoader, {}),
    ".md":  (UnstructuredMarkdownLoader, {}),
    ".txt": (TextLoader, {"encoding": "utf-8"}),
    ".py":  (TextLoader, {"encoding": "utf-8"}),
    ".js":  (TextLoader, {"encoding": "utf-8"}),
    ".ts":  (TextLoader, {"encoding": "utf-8"}),
    ".json":(TextLoader, {"encoding": "utf-8"}),
    ".yaml":(TextLoader, {"encoding": "utf-8"}),
    ".yml": (TextLoader, {"encoding": "utf-8"}),
    ".toml":(TextLoader, {"encoding": "utf-8"}),
    ".rst": (TextLoader, {"encoding": "utf-8"}),
    ".csv": (TextLoader, {"encoding": "utf-8"}),
}


def _check_api_key():
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        sys.exit(
            "Error: OPENAI_API_KEY is not set.\n"
            "  export OPENAI_API_KEY=sk-..."
        )


def _embeddings():
    return OpenAIEmbeddings(model=EMBED_MODEL,base_url="https://api.tokenfactory.nebius.com/v1/",api_key=os.environ.get("OPENAI_API_KEY"))


def _vectorstore(embeddings):
    return Chroma(
        collection_name=COLLECTION,
        embedding_function=embeddings,
        persist_directory=str(CHROMA_DIR),
    )


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_embed(folder: str):
    folder_path = Path(folder).resolve()
    if not folder_path.is_dir():
        sys.exit(f"Error: '{folder_path}' is not a directory.")

    print(f"Scanning: {folder_path}")

    # Load each supported file individually so we can track progress
    docs = []
    files = [
        f for f in folder_path.rglob("*")
        if f.is_file() and f.suffix.lower() in LOADER_MAP
    ]

    if not files:
        sys.exit(
            f"No supported files found in '{folder_path}'.\n"
            f"Supported: {', '.join(LOADER_MAP)}"
        )

    for f in files:
        loader_cls, loader_kwargs = LOADER_MAP[f.suffix.lower()]
        try:
            loader = loader_cls(str(f), **loader_kwargs)
            loaded = loader.load()
            # Tag source metadata
            for doc in loaded:
                doc.metadata.setdefault("source", str(f))
            docs.extend(loaded)
            print(f"  Loaded  {f.relative_to(folder_path)}  ({len(loaded)} chunk(s))")
        except Exception as exc:
            print(f"  WARNING: skipped {f.name} — {exc}")

    print(f"\nTotal docs loaded: {len(docs)}")

    # Split into chunks
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""],
    )
    chunks = splitter.split_documents(docs)
    print(f"Total chunks after splitting: {len(chunks)}")

    # Embed + store
    _check_api_key()
    embeddings = _embeddings()
    print(f"\nEmbedding with '{EMBED_MODEL}' …")
    vs = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        collection_name=COLLECTION,
        persist_directory=str(CHROMA_DIR),
    )
    print(f"Stored {vs._collection.count()} vectors in {CHROMA_DIR}")


def cmd_query(question: str, k: int = DEFAULT_K):
    _check_api_key()
    embeddings = _embeddings()
    vs = _vectorstore(embeddings)

    count = vs._collection.count()
    if count == 0:
        sys.exit("ChromaDB is empty. Run `embed <folder>` first.")

    print(f"Querying {count} vectors (top-{k}) …\n")

    llm = ChatOpenAI(model=LLM_MODEL, temperature=0, base_url="https://api.tokenfactory.nebius.com/v1/",api_key=os.environ.get("OPENAI_API_KEY"))
    prompt = PromptTemplate(
        template=PROMPT_TEMPLATE,
        input_variables=["context", "question"],
    )

    chain = RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=vs.as_retriever(search_kwargs={"k": k}),
        return_source_documents=True,
        chain_type_kwargs={"prompt": prompt},
    )

    result = chain.invoke({"query": question})

    print("Answer:")
    print("─" * 60)
    print(result["result"])
    print("\nSources:")
    seen = set()
    for doc in result["source_documents"]:
        src = doc.metadata.get("source", "unknown")
        if src not in seen:
            print(f"  • {src}")
            seen.add(src)


def cmd_clear():
    import shutil
    if CHROMA_DIR.exists():
        shutil.rmtree(CHROMA_DIR)
        print(f"Cleared: {CHROMA_DIR}")
    else:
        print("Nothing to clear.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Simple RAG: embed a folder, then query it.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_embed = sub.add_parser("embed", help="Embed documents from a folder")
    p_embed.add_argument("folder", help="Path to the folder to embed")

    p_query = sub.add_parser("query", help="Ask a question against embedded docs")
    p_query.add_argument("question", help="Your question (wrap in quotes)")
    p_query.add_argument(
        "-k", type=int, default=DEFAULT_K,
        help=f"Number of chunks to retrieve (default: {DEFAULT_K})"
    )

    sub.add_parser("clear", help="Delete the ChromaDB store")

    args = parser.parse_args()

    if args.cmd == "embed":
        cmd_embed(args.folder)
    elif args.cmd == "query":
        cmd_query(args.question, args.k)
    elif args.cmd == "clear":
        cmd_clear()


if __name__ == "__main__":
    main()

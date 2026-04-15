"""
StixDB adapter for LongMemEval.

Implements the retrieval interface expected by LongMemEval:
  retrieve(query, corpus, corpus_ids, k) -> List[int]   # ranked indices into corpus

Each call:
  1. Stores corpus documents into a temporary StixDB collection
  2. Runs hybrid search for the query
  3. Maps returned node IDs back to corpus indices
  4. Deletes the collection (unless --keep-collections is set)

The adapter also exposes:
  retrieve_and_answer(question, sessions, session_ids, dates, top_k)
for the end-to-end QA evaluation mode using engine.ask().
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class StixDBRetriever:
    """
    Wraps StixDBEngine (REST client) to serve as a LongMemEval retrieval backend.

    Parameters
    ----------
    url:
        StixDB server URL.
    api_key:
        Optional API key.
    collection_prefix:
        Prefix for temporary collection names (default: "lme_bench").
    keep_collections:
        If True, do not delete collections after each question — useful for
        debugging but uses more memory.
    mode:
        Retrieval mode: "hybrid" (default), "keyword", "semantic".
    granularity:
        "session" (whole session per node) or "turn" (one node per user turn).
    """

    def __init__(
        self,
        url: str = "http://localhost:4020",
        api_key: Optional[str] = None,
        collection_prefix: str = "lme_bench",
        keep_collections: bool = False,
        mode: str = "hybrid",
        granularity: str = "session",
    ) -> None:
        from stixdb import StixDBEngine, StixDBConfig
        self.engine = StixDBEngine(config=StixDBConfig(url=url, api_key=api_key, timeout=120.0))
        self.prefix = collection_prefix
        self.keep = keep_collections
        self.mode = mode
        self.granularity = granularity
        self._counter = 0

    def _next_collection(self) -> str:
        self._counter += 1
        return f"{self.prefix}_{self._counter:05d}"

    # ── Public sync interface (wraps async) ─────────────────────────────── #

    def retrieve(
        self,
        query: str,
        corpus: list[str],
        corpus_ids: list[str],
        k: int = 10,
    ) -> list[int]:
        """
        LongMemEval retrieval interface.

        Parameters
        ----------
        query:
            Question text.
        corpus:
            List of document texts (sessions or turns).
        corpus_ids:
            Parallel list of document IDs (session_id or session_id_turn_N).
        k:
            Number of top documents to return.

        Returns
        -------
        List of indices into corpus, ranked best-first (length ≤ k).
        """
        return asyncio.get_event_loop().run_until_complete(
            self._aretrieve(query, corpus, corpus_ids, k)
        )

    def retrieve_and_answer(
        self,
        question: str,
        corpus: list[str],
        corpus_ids: list[str],
        k: int = 10,
        question_date: Optional[str] = None,
    ) -> tuple[list[int], str]:
        """
        Retrieve + generate answer using engine.ask().

        Returns (ranked_indices, answer_markdown).
        """
        return asyncio.get_event_loop().run_until_complete(
            self._aretrieve_and_answer(question, corpus, corpus_ids, k, question_date)
        )

    # ── Async implementation ─────────────────────────────────────────────── #

    async def _aretrieve(
        self,
        query: str,
        corpus: list[str],
        corpus_ids: list[str],
        k: int,
    ) -> list[int]:
        coll = self._next_collection()
        try:
            await self._ingest_corpus(coll, corpus, corpus_ids)
            return await self._search(coll, query, corpus_ids, k)
        finally:
            if not self.keep:
                try:
                    await self.engine.delete_collection(collection=coll)
                except Exception:
                    pass

    async def _aretrieve_and_answer(
        self,
        question: str,
        corpus: list[str],
        corpus_ids: list[str],
        k: int,
        question_date: Optional[str],
    ) -> tuple[list[int], str]:
        coll = self._next_collection()
        try:
            await self._ingest_corpus(coll, corpus, corpus_ids)
            indices = await self._search(coll, question, corpus_ids, k)

            date_prefix = f"[As of {question_date}] " if question_date else ""
            response = await self.engine.ask(
                collection=coll,
                question=date_prefix + question,
                top_k=k,
                depth=2,
                mode=self.mode,
            )
            return indices, response.answer
        finally:
            if not self.keep:
                try:
                    await self.engine.delete_collection(collection=coll)
                except Exception:
                    pass

    async def _ingest_corpus(
        self,
        collection: str,
        corpus: list[str],
        corpus_ids: list[str],
    ) -> None:
        """Bulk-store corpus documents as episodic nodes."""
        items = [
            {
                "content": text,
                "node_id": cid,
                "node_type": "experience",
                "tier": "episodic",
                "importance": 0.7,
                "tags": ["longmemeval", self.granularity],
                "metadata": {"corpus_id": cid},
            }
            for text, cid in zip(corpus, corpus_ids)
        ]
        await self.engine.bulk_store(collection=collection, items=items)

    async def _search(
        self,
        collection: str,
        query: str,
        corpus_ids: list[str],
        k: int,
    ) -> list[int]:
        """Run hybrid retrieval and map node IDs back to corpus indices."""
        id_to_index = {cid: i for i, cid in enumerate(corpus_ids)}

        results = await self.engine.retrieve(
            collection=collection,
            query=query,
            top_k=k,
            threshold=0.0,   # return everything ranked, let k do the cutting
            depth=1,
            mode=self.mode,
        )

        ranked: list[int] = []
        seen: set[int] = set()
        for node in results:
            nid = node.get("id") or node.get("node_id", "")
            idx = id_to_index.get(nid)
            if idx is not None and idx not in seen:
                ranked.append(idx)
                seen.add(idx)
            if len(ranked) >= k:
                break

        return ranked

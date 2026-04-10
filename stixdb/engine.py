"""
StixDBEngine — top-level API for the StixDB Agentic Context Database.

This is the single object that users / applications interact with.
Everything else is internal.

Usage:
    from stixdb import StixDBEngine, StixDBConfig

    engine = StixDBEngine()             # Defaults: in-memory, no LLM
    await engine.start()

    # Store memories
    await engine.store(
        collection="my_agent",
        content="User prefers dark mode in all UIs",
        node_type="fact",
        tags=["ui", "preferences"],
    )

    # Agentic query
    response = await engine.ask("my_agent", "What UI preferences does the user have?")
    print(response.answer)
    print(response.reasoning_trace)
    print([s.content for s in response.sources])

    await engine.stop()
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
from pathlib import Path
from typing import Any, Optional, AsyncIterator

import numpy as np

import structlog

from stixdb.config import StixDBConfig, StorageMode, VectorBackend, LLMProvider  # noqa: F401
from stixdb.graph.memory_graph import MemoryGraph
from stixdb.graph.summary_index import (
    build_connection_entries,
    build_summary_connection_index,
    merge_summary_connection_index,
)
from stixdb.graph.node import NodeType, MemoryTier
from stixdb.graph.edge import RelationType
from stixdb.graph.cluster import ClusterType
from stixdb.storage.networkx_backend import NetworkXBackend
from stixdb.storage.vector_store import build_vector_store
from stixdb.storage.embeddings import build_embedding_client
from stixdb.backup import build_backup_store
from stixdb.ingestion import extract_document_segments, is_supported_text_file
from stixdb.agent.maintenance import MaintenancePlanner, MaintenanceQuestion
from stixdb.agent.memory_agent import MemoryAgent
from stixdb.agent.reasoner import Reasoner, ReasoningResult
from stixdb.agent.sessions import SessionManager
from stixdb.context.broker import ContextBroker
from stixdb.context.response import ContextResponse, SourceNode
from stixdb.observability.tracer import init_tracer, get_tracer

logger = structlog.get_logger(__name__)


class StixDBEngine:
    """
    StixDB Agentic Context Database Engine.
    
    One engine instance can manage multiple collections.
    Each collection has its own isolated MemoryGraph and MemoryAgent.
    
    Thread / async safety:
        - All public methods are async-safe.
        - `store()` and `ask()` can be called concurrently from multiple tasks.
        - Each collection's agent runs in its own background task.
    """

    def __init__(self, config: Optional[StixDBConfig] = None) -> None:
        self.config = config or StixDBConfig.from_env()
        self._started = False

        # Per-collection instances (lazily created by _ensure_collection)
        self._graphs: dict[str, MemoryGraph] = {}
        self._agents: dict[str, MemoryAgent] = {}
        self._brokers: dict[str, ContextBroker] = {}
        self._maintenance_fingerprints: dict[str, str] = {}

        # Shared infrastructure
        self.sessions = SessionManager()
        self.maintenance_planner = MaintenancePlanner()
        self._storage_backend = self._build_storage_backend()
        self._vector_store = build_vector_store(
            backend=self.config.storage.vector_backend,
            embedding_dim=self.config.embedding.dimensions,
            data_dir=self.config.storage.data_dir,
            chroma_host=self.config.storage.chroma_host,
            qdrant_host=self.config.storage.qdrant_host,
            qdrant_port=self.config.storage.qdrant_port,
        )
        self._embedding_client = build_embedding_client(self.config.embedding)
        self._backup_store = build_backup_store(self.config.backup)

    def _build_storage_backend(self):
        if self.config.storage.mode == StorageMode.NEO4J:
            try:
                from stixdb.storage.neo4j_backend import Neo4jBackend
                return Neo4jBackend(
                    uri=self.config.storage.neo4j_uri,
                    user=self.config.storage.neo4j_user,
                    password=self.config.storage.neo4j_password,
                )
            except ImportError:
                logger.warning("Neo4j driver not installed — falling back to KuzuDB backend.")
                return self._build_kuzu_backend()

        if self.config.storage.mode == StorageMode.KUZU:
            return self._build_kuzu_backend()

        # Default: in-memory NetworkX (no persistence)
        return NetworkXBackend()

    def _build_kuzu_backend(self):
        try:
            from stixdb.storage.kuzu_backend import KuzuBackend
            logger.info(
                "Using KuzuDB persistent storage",
                path=self.config.storage.kuzu_path,
                buffer_pool_mb=self.config.storage.kuzu_buffer_pool_mb,
            )
            return KuzuBackend(
                db_path=self.config.storage.kuzu_path,
                buffer_pool_mb=self.config.storage.kuzu_buffer_pool_mb,
            )
        except ImportError:
            logger.warning(
                "kuzu package not installed — falling back to in-memory NetworkX backend.\n"
                "Install kuzu:  pip install kuzu"
            )
            return NetworkXBackend()

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        """
        Start the engine. Must be called before any store/ask operations.
        Initialises observability. Collections are initialised lazily.
        """
        if self._started:
            return

        # Configure logging
        structlog.configure(
            wrapper_class=structlog.make_filtering_bound_logger(
                getattr(__import__("logging"), self.config.log_level, 20)
            )
        )

        # Start observability
        tracer = init_tracer(
            enable_metrics=self.config.enable_metrics,
            metrics_port=self.config.metrics_port,
        )
        if self.config.enable_metrics:
            tracer.start_metrics_server()

        self._started = True
        for collection in await self._storage_backend.list_collections():
            await self._ensure_collection(collection)
        logger.info("StixDB Engine started", storage=self.config.storage.mode.value, llm=self.config.reasoner.provider.value)

    async def stop(self) -> None:
        """Gracefully stop all collection agents and close storage."""
        for collection, agent in self._agents.items():
            logger.info("Stopping agent", collection=collection)
            await agent.stop()
        await self._storage_backend.close()
        await self._vector_store.close()
        self._started = False
        logger.info("StixDB Engine stopped")

    def _assert_started(self) -> None:
        if not self._started:
            raise RuntimeError("StixDBEngine is not started. Call `await engine.start()` first.")

    # ------------------------------------------------------------------ #
    # Collection management                                                #
    # ------------------------------------------------------------------ #

    async def _ensure_collection(self, collection: str) -> tuple[MemoryGraph, MemoryAgent, ContextBroker]:
        """Lazily initialise a collection if it doesn't exist."""
        if collection not in self._graphs:
            graph = MemoryGraph(
                collection=collection,
                storage=self._storage_backend,
                vector_store=self._vector_store,
                embedding_client=self._embedding_client,
            )
            await graph.initialize()

            agent = MemoryAgent(graph=graph, config=self.config.agent)
            broker = ContextBroker(
                graph=graph,
                agent=agent,
                reasoner_config=self.config.reasoner,
                verbose=self.config.verbose,
            )

            # Patch LLM synthesis into the consolidator now that the broker
            # (and its reasoner) exists. The consolidator uses this to generate
            # meaningful summaries instead of raw concatenations.
            async def _synthesize(nodes, _r=broker.reasoner):
                return await _r.synthesize_nodes(nodes)
            agent.consolidator._synthesize_fn = _synthesize

            async def maintenance_callback(bound_collection: str = collection) -> dict:
                return await self._run_collection_maintenance(bound_collection)
            agent.set_maintenance_callback(maintenance_callback)

            self._graphs[collection] = graph
            self._agents[collection] = agent
            self._brokers[collection] = broker

            # Start the background agent
            await agent.start()

            logger.info("Collection initialised", collection=collection)

        return self._graphs[collection], self._agents[collection], self._brokers[collection]

    async def drop_collection(self, collection: str) -> None:
        """Stop the collection's agent and remove all its data."""
        if collection in self._agents:
            await self._agents[collection].stop()
            del self._agents[collection]
        self._graphs.pop(collection, None)
        self._brokers.pop(collection, None)
        logger.info("Collection dropped", collection=collection)

    async def delete_collection(self, collection: str) -> dict:
        """
        Delete all data for a collection, then unload it.

        Returns a summary with deletion counts.
        """
        self._assert_started()

        graph, _, _ = await self._ensure_collection(collection)
        total_nodes = await graph.count_nodes()
        total_clusters = len(await graph.list_clusters())

        deleted = await graph.delete_collection()

        await self.drop_collection(collection)

        logger.info(
            "Collection deleted",
            collection=collection,
            deleted_nodes=total_nodes,
            deleted_clusters=total_clusters,
        )
        return {
            "collection": collection,
            "deleted": deleted,
            "deleted_nodes": total_nodes,
            "deleted_clusters": total_clusters,
        }

    def list_collections(self) -> list[str]:
        return list(self._graphs.keys())

    async def list_collections_async(self) -> list[str]:
        loaded = set(self._graphs.keys())
        persisted = set(await self._storage_backend.list_collections())
        return sorted(loaded | persisted)

    # ------------------------------------------------------------------ #
    # Memory Storage                                                       #
    # ------------------------------------------------------------------ #

    async def store(
        self,
        collection: str,
        content: str,
        node_type: str = "fact",
        tier: str = "episodic",
        importance: float = 0.5,
        source: Optional[str] = None,
        source_agent_id: Optional[str] = None,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict] = None,
        pinned: bool = True,
        node_id: Optional[str] = None,
    ) -> str:
        """
        Store a new memory node in a collection.
        
        Returns the node ID of the stored memory.
        
        The engine will:
        - Compute and store the embedding
        - Index it in the vector store
        - Notify the agent of the new node
        """
        self._assert_started()
        graph, agent, _ = await self._ensure_collection(collection)

        node = await graph.add_node(
            content=content,
            node_type=NodeType(node_type),
            tier=MemoryTier(tier),
            importance=importance,
            source=source,
            source_agent_id=source_agent_id,
            tags=tags or [],
            metadata=metadata or {},
            pinned=pinned,
            node_id=node_id,
        )

        get_tracer().record_node_stored(collection, node.id, content[:80])
        return node.id

    async def bulk_store(
        self,
        collection: str,
        items: list[dict],
    ) -> list[str]:
        """
        Store multiple memories in a single batched operation.
        More efficient than calling store() in a loop.
        
        Each item is a dict matching the store() kwargs.
        """
        self._assert_started()
        graph, _, _ = await self._ensure_collection(collection)
        nodes = await graph.bulk_add_nodes(items)
        return [n.id for n in nodes]

    async def ingest_file(
        self,
        collection: str,
        filepath: str | list,
        source_name: Optional[str] = None,
        tags: Optional[list[str]] = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        parser: str = "auto",
    ) -> list[str]:
        """Ingest a file path or a list of LangChain Document objects into the graph.

        When ``filepath`` is a list the items are treated as LangChain
        ``Document`` objects (or plain dicts with a ``page_content`` key).
        File I/O and backup upload are skipped; a content hash is derived from
        the combined text so deduplication still works across repeated calls
        with the same payload.
        """
        self._assert_started()
        graph, _, _ = await self._ensure_collection(collection)

        _is_docs = isinstance(filepath, list)

        if _is_docs:
            source_name = source_name or "langchain_documents"
            combined = "".join(
                (d.page_content if hasattr(d, "page_content") else str(d))
                for d in filepath
            )
            document_hash = self._hash_text(combined)
            backup_ref = None
        else:
            if not os.path.exists(filepath):
                raise FileNotFoundError(f"File {filepath} not found.")
            source_name = source_name or os.path.basename(filepath)
            with open(filepath, "rb") as raw_file:
                document_bytes = raw_file.read()
            document_hash = hashlib.sha1(document_bytes).hexdigest()
            backup_ref = await self._backup_store.upload_file(
                collection=collection,
                filepath=filepath,
                source_name=source_name,
            )

        def chunk_text(text: str) -> list[tuple[str, int, int]]:
            chunks: list[tuple[str, int, int]] = []
            start = 0
            step = max(1, chunk_size - chunk_overlap)
            while start < len(text):
                end = min(len(text), start + chunk_size)
                chunk = text[start:end]
                chunks.append((chunk, start, end))
                if end >= len(text):
                    break
                start += step
            return chunks

        existing_nodes = await graph.list_nodes(limit=20000)

        # ── Step 1: Delete all existing chunks from the same source file ──────
        # Deduplication by (document_hash, chunk_index) breaks whenever the file
        # is modified — the hash changes, so old chunks linger as duplicates.
        # Instead: treat re-ingestion of a source as a full replace.
        if source_name:
            stale = [n for n in existing_nodes if n.source == source_name]
            for n in stale:
                await graph.delete_node(n.id)
            if stale:
                logger.info(
                    "Replaced stale chunks for source",
                    source=source_name,
                    deleted=len(stale),
                    collection=collection,
                )

        # ── Step 2: Build content-hash set for cross-source dedup guard ───────
        # Prevents identical chunk text from being stored twice even from
        # different source paths (e.g. copied files).
        existing_content_hashes = {
            (node.metadata or {}).get("content_hash")
            for node in existing_nodes
            if (node.metadata or {}).get("content_hash")
        }

        ingested_at = time.time()
        extraction = extract_document_segments(filepath, parser=parser)

        items = []
        chunk_index = 0
        for segment in extraction.segments:
            segment_text = segment.get("text", "")
            segment_metadata = dict(segment.get("metadata") or {})
            for chunk, char_start, char_end in chunk_text(segment_text):
                if not chunk.strip():
                    continue
                items.append({
                    "content": chunk,
                    "node_type": "fact",
                    "tier": "episodic",
                    "importance": 0.5,
                    "source": source_name,
                    "tags": tags or ["ingestion"],
                    "metadata": {
                        "chunk": chunk_index,
                        "filepath": None if _is_docs else filepath,
                        "filename": source_name,
                        "filetype": extraction.filetype,
                        "parser_used": extraction.parser_used,
                        "document_hash": document_hash,
                        "chunk_hash": self._hash_text(chunk),
                        "content_hash": self._hash_text(chunk),
                        "char_start": char_start,
                        "char_end": char_end,
                        "ingested_at": ingested_at,
                        **segment_metadata,
                        **({"backup": backup_ref} if backup_ref else {}),
                    },
                    # Ingested chunks are NOT pinned — they should be eligible
                    # for consolidation, synthesis, and archiving.  Only
                    # explicitly user-created nodes should be pinned.
                    "pinned": False,
                })
                chunk_index += 1

        # Secondary guard: skip chunks whose exact content already exists
        # (catches identical chunks from other sources / LangChain doc re-use)
        items = [
            item for item in items
            if item["metadata"].get("content_hash") not in existing_content_hashes
        ]

        if not items:
            return []

        nodes = await graph.bulk_add_nodes(items)
        await self._sync_chunks_with_summaries(graph, nodes)
        return [n.id for n in nodes]

    async def _sync_chunks_with_summaries(
        self,
        graph: MemoryGraph,
        new_nodes: list,
    ) -> None:
        """
        After ingestion, link each new chunk to the most semantically similar
        existing SUMMARY node (if any). When a match is found:
          - A DERIVED_FROM edge is added (summary → chunk) so the summary
            is aware of this new piece of evidence.
          - The summary's embedding is updated to the normalised centroid of
            its old embedding and the chunk's embedding.
          - The chunk's node ID is appended to the summary's source lineage.

        This keeps summaries coherent as new content arrives and prevents the
        consolidation cycle from creating duplicate summaries for content that
        is already represented.
        """
        threshold = self.config.agent.consolidation_similarity_threshold

        summary_nodes = await graph.list_nodes(node_type="summary", limit=5000)
        summaries_with_emb = [
            (s, np.array(s.embedding, dtype=np.float32))
            for s in summary_nodes
            if s.embedding is not None
        ]
        if not summaries_with_emb:
            return

        for chunk_node in new_nodes:
            if chunk_node.embedding is None:
                continue
            chunk_emb = np.array(chunk_node.embedding, dtype=np.float32)

            # Find the single most similar summary above threshold
            best_sim = -1.0
            best_summary = None
            best_summary_emb = None
            for summary, summary_emb in summaries_with_emb:
                sim = float(np.clip(np.dot(chunk_emb, summary_emb), -1.0, 1.0))
                if sim >= threshold and sim > best_sim:
                    best_sim = sim
                    best_summary = summary
                    best_summary_emb = summary_emb

            if best_summary is None:
                continue

            # Link the chunk as a new evidence source for this summary
            await graph.add_edge(
                source_id=best_summary.id,
                target_id=chunk_node.id,
                relation_type=RelationType.DERIVED_FROM,
                weight=best_sim,
                created_by="ingest-sync",
                metadata={"sync_similarity": best_sim, "sync_type": "chunk_summary_sync"},
            )

            # Update the summary's embedding centroid to include this chunk
            new_emb = (best_summary_emb + chunk_emb) / 2.0
            norm = np.linalg.norm(new_emb)
            if norm > 0:
                new_emb = new_emb / norm
            best_summary.set_embedding(new_emb)

            lineage = best_summary.metadata.get("source_lineage", [])
            lineage.append({
                "node_id": chunk_node.id,
                "source": chunk_node.source,
                "synced_at": time.time(),
                "sync_similarity": best_sim,
            })
            best_summary.metadata["source_lineage"] = lineage
            best_summary.metadata["connection_index"] = merge_summary_connection_index(
                best_summary.metadata,
                summary_id=best_summary.id,
                summary_kind=str(best_summary.metadata.get("summary_kind") or "synced_summary"),
                source=best_summary.source or "agent-maintenance",
                content_hash=self._hash_text(best_summary.content),
                entries=build_connection_entries(
                    [chunk_node.id],
                    relation_type=RelationType.DERIVED_FROM,
                    role="sync_evidence",
                    weight=max(0.6, best_sim),
                    source="ingest-sync",
                ),
            )
            best_summary.parent_node_ids = sorted(set(best_summary.parent_node_ids) | {chunk_node.id})
            await graph.update_node(best_summary)

            logger.info(
                "Synced ingested chunk with existing summary",
                summary_id=best_summary.id[:8],
                chunk_id=chunk_node.id[:8],
                similarity=f"{best_sim:.3f}",
                collection=graph.collection,
            )

    async def ingest_folder(
        self,
        collection: str,
        folderpath: str,
        tags: Optional[list[str]] = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        parser: str = "auto",
        recursive: bool = True,
    ) -> dict:
        """Ingest all supported text-like files from a folder."""
        self._assert_started()
        root = Path(folderpath)
        if not root.exists():
            raise FileNotFoundError(f"Folder {folderpath} not found.")
        if not root.is_dir():
            raise NotADirectoryError(f"{folderpath} is not a directory.")

        iterator = root.rglob("*") if recursive else root.glob("*")
        ingested: list[dict] = []
        skipped: list[str] = []

        for path in iterator:
            if not path.is_file():
                continue
            if not is_supported_text_file(path):
                skipped.append(str(path))
                continue
            node_ids = await self.ingest_file(
                collection=collection,
                filepath=str(path),
                source_name=str(path.relative_to(root)),
                tags=tags,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                parser=parser,
            )
            ingested.append(
                {
                    "filepath": str(path),
                    "source_name": str(path.relative_to(root)),
                    "node_ids": node_ids,
                    "ingested_chunks": len(node_ids),
                }
            )

        return {
            "collection": collection,
            "folder": str(root),
            "files_processed": len(ingested),
            "files_skipped": len(skipped),
            "ingested": ingested,
            "skipped": skipped,
        }

    async def add_relation(
        self,
        collection: str,
        source_node_id: str,
        target_node_id: str,
        relation_type: str = "relates_to",
        weight: float = 1.0,
        confidence: float = 1.0,
        created_by: str = "system",
        metadata: Optional[dict] = None,
        edge_id: Optional[str] = None,
    ) -> str:
        """Manually add a typed edge between two nodes."""
        self._assert_started()
        graph, _, _ = await self._ensure_collection(collection)
        edge = await graph.add_edge(
            source_id=source_node_id,
            target_id=target_node_id,
            relation_type=RelationType(relation_type),
            weight=weight,
            confidence=confidence,
            created_by=created_by,
            metadata=metadata or {},
            edge_id=edge_id,
        )
        return edge.id

    # ------------------------------------------------------------------ #
    # Agentic Query                                                        #
    # ------------------------------------------------------------------ #

    async def ask(
        self,
        collection: str,
        question: str,
        top_k: int = 15,
        threshold: float = 0.25,
        depth: int = 2,
        system_prompt: Optional[str] = None,
        output_schema: Optional[dict] = None,
        thinking_steps: int = 1,
        hops_per_step: int = 4,
        max_tokens: Optional[int] = None,
    ) -> ContextResponse:
        """
        Ask the StixDB agent a natural-language question.

        When thinking_steps > 1, the engine runs the multi-hop reasoning loop
        (recursive_chat) which issues multiple retrieval hops per step, refines
        its search query based on what it finds, and checks confidence before
        stopping.  This produces richer answers for complex questions at the
        cost of more LLM calls.

        Args:
            thinking_steps: Number of reasoning steps (1 = single-pass, ≥2 = multi-hop).
            hops_per_step:  Max retrieval hops within each thinking step.
        """
        self._assert_started()
        if thinking_steps > 1:
            return await self.recursive_chat(
                collection=collection,
                question=question,
                thinking_steps=thinking_steps,
                hops_per_step=hops_per_step,
                threshold=max(threshold, 0.25),
            )
        _, _, broker = await self._ensure_collection(collection)
        response = await broker.ask(
            question=question,
            top_k=top_k,
            search_threshold=threshold,
            graph_depth=depth,
            system_prompt=system_prompt,
            output_schema=output_schema,
            max_tokens=max_tokens,
            query_origin="user",
        )

        # Persist reasoning as a traversable sub-node when the answer is confident.
        # This builds a knowledge graph of Q→A→R→sources for future traversal,
        # so similar future questions can follow reasoning edges to find richer context.
        if (
            response.reasoning_trace
            and response.confidence >= 0.65
            and response.sources
        ):
            try:
                # Store the answer itself as a node so the reasoning can link to it
                graph = self._graphs[collection]
                answer_text = str(response.answer or "").strip()
                if answer_text and self._is_useful_maintenance_answer(answer_text):
                    answer_key = self._hash_text(f"answer:{question.strip().lower()}")
                    # Find or create the answer node
                    all_facts = await graph.list_nodes(node_type="fact", limit=10000)
                    answer_node = next(
                        (n for n in all_facts
                         if (n.metadata or {}).get("answer_key") == answer_key),
                        None,
                    )
                    if answer_node is None:
                        answer_node = await graph.add_node(
                            content=answer_text,
                            node_type=NodeType.FACT,
                            tier=MemoryTier.EPISODIC,
                            importance=min(0.9, 0.5 + response.confidence * 0.4),
                            source="agent-answer",
                            tags=["user-query", "answer"],
                            metadata={
                                "answer_key": answer_key,
                                "question": question,
                                "confidence": response.confidence,
                            },
                        )
                    await self._upsert_reasoning_subnode(
                        collection=collection,
                        parent_node_id=answer_node.id,
                        reasoning_trace=response.reasoning_trace,
                        source_node_ids=[s.node_id for s in response.sources[:8]],
                        question=question,
                        label=f"Q: {question[:80]}",
                        confidence=response.confidence,
                    )
            except Exception as exc:
                logger.debug("Failed to persist user query reasoning subgraph", error=str(exc))

        return response

    async def retrieve(
        self,
        collection: str,
        query: str,
        top_k: int = 10,
        threshold: float = 0.25,
        depth: int = 1,
    ) -> list[dict]:
        """
        Raw retrieval without LLM reasoning.
        Returns a list of serialised node dicts with scores.
        """
        self._assert_started()
        _, _, broker = await self._ensure_collection(collection)
        candidates = await broker.retrieve_only(
            query=query, top_k=top_k, threshold=threshold, depth=depth
        )
        return [
            {**node.to_dict(include_embedding=False), "score": score}
            for node, score in candidates
        ]

    async def chat(
        self,
        collection: str,
        question: str,
        session_id: Optional[str] = None,
        top_k: int = 15,
        threshold: float = 0.25,
        depth: int = 2,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> ContextResponse:
        """
        Multi-turn chat with session history.
        """
        self._assert_started()
        _, _, broker = await self._ensure_collection(collection)
        
        history = []
        if session_id:
            session = self.sessions.get_session(session_id)
            history = session.get_history()
            
        # We need to update ContextBroker.ask to handle history, 
        # or just pass it to the reasoner here.
        # For simplicity, we'll let the broker handle the retrieval, 
        # but the reasoner gets the history.
        
        # NOTE: In a full implementation, the history should also be used 
        # for query expansion/intent detection.
        
        response = await broker.ask(
            question=question,
            top_k=top_k,
            search_threshold=threshold,
            graph_depth=depth,
            history=history,
            temperature=temperature,
            max_tokens=max_tokens,
            query_origin="user",
        )
        
        if session_id:
            session.add_message("user", question)
            session.add_message("assistant", str(response.answer))
            
        return response

    async def _run_collection_maintenance(self, collection: str) -> dict:
        if collection not in self._graphs:
            return {"updated": 0, "questions": []}

        graph = self._graphs[collection]
        broker = self._brokers[collection]
        nodes = await graph.list_nodes(limit=5000)
        if not nodes:
            return {"updated": 0, "questions": []}

        fingerprint = self._collection_maintenance_fingerprint(nodes)
        if self._maintenance_fingerprints.get(collection) == fingerprint:
            return {"updated": 0, "questions": []}

        plans = self.maintenance_planner.plan(collection=collection, nodes=nodes)
        updated = 0
        for plan in plans:
            response = await broker.ask(
                question=plan.question,
                top_k=8,
                search_threshold=0.2,
                graph_depth=1,
                temperature=0.1,
                max_tokens=300,
                enable_reflection_cache=False,
                query_origin="maintenance",
            )
            answer = str(response.answer or "").strip()
            # Skip storing if the LLM returned nothing useful — an empty or
            # error-phrase answer produces a node that actively misleads retrieval.
            if not self._is_useful_maintenance_answer(answer):
                logger.debug(
                    "Skipping maintenance summary — answer is empty or low-quality",
                    collection=collection,
                    label=plan.summary_label,
                    answer_preview=answer[:80],
                )
                continue
            summary_node_id = await self._upsert_maintenance_summary(
                collection=collection,
                plan=plan,
                answer=answer,
                reasoning_trace=response.reasoning_trace,
                source_node_ids=[source.node_id for source in response.sources[:8]],
            )
            # Store the reasoning trace as a linked sub-node for graph traversal
            if summary_node_id and response.reasoning_trace:
                await self._upsert_reasoning_subnode(
                    collection=collection,
                    parent_node_id=summary_node_id,
                    reasoning_trace=response.reasoning_trace,
                    source_node_ids=[source.node_id for source in response.sources[:8]],
                    question=plan.question,
                    label=plan.summary_label,
                    confidence=response.confidence,
                )
            updated += 1

        self._maintenance_fingerprints[collection] = fingerprint
        return {
            "updated": updated,
            "questions": [plan.question for plan in plans],
            "reasons": [plan.reason for plan in plans],
        }

    _MAINTENANCE_GARBAGE_PHRASES = (
        "returned an empty response",
        "no answer",
        "no relevant",
        "i don't have",
        "i do not have",
        "cannot answer",
        "not enough information",
        "no information",
        "unable to",
        "i couldn't find",
        "i could not find",
    )

    def _is_useful_maintenance_answer(self, answer: str) -> bool:
        """
        Return True only if the answer is worth storing as a maintenance node.

        Rejects:
        - Blank / whitespace-only strings
        - Very short answers (< 30 chars) — too thin to be useful
        - Answers that are raw JSON fragments (truncated LLM output)
        - Common LLM error phrases (empty context, no info, etc.)
        """
        if not answer or len(answer) < 30:
            return False
        stripped = answer.strip()
        # Raw JSON / dict responses — LLM returned structured data instead of prose
        if stripped.startswith("{") or stripped.startswith("["):
            return False
        lower = stripped.lower()
        for phrase in self._MAINTENANCE_GARBAGE_PHRASES:
            if phrase in lower:
                return False
        return True

    async def _upsert_maintenance_summary(
        self,
        collection: str,
        plan: MaintenanceQuestion,
        answer: str,
        source_node_ids: list[str],
        reasoning_trace: str = "",
    ) -> Optional[str]:
        """Returns the node ID of the created/updated summary node."""
        graph = self._graphs[collection]
        question_key = plan.question_key
        support_node_ids = await self._select_summary_support_nodes(
            collection=collection,
            candidate_ids=source_node_ids + plan.focus_node_ids,
            limit=4,
        )
        content = f"{plan.summary_label}\n\n{answer}"
        existing_nodes = await graph.list_nodes(node_type="summary", limit=5000)
        existing = next(
            (
                node for node in existing_nodes
                if (node.metadata or {}).get("question_key") == question_key
                and node.source == "agent-maintenance"
            ),
            None,
        )
        connection_entries = build_connection_entries(
            support_node_ids,
            relation_type=RelationType.SUMMARIZES,
            role="support",
            weight=1.0,
            source="agent-maintenance",
        )
        connection_entries.extend(
            build_connection_entries(
                plan.focus_node_ids,
                relation_type=RelationType.REFERENCES,
                role="focus",
                weight=0.8,
                source="agent-maintenance",
            )
        )
        metadata = {
            "question": plan.question,
            "question_key": question_key,
            "synthesized_from": support_node_ids,
            "content_hash": self._hash_text(content),
            "summary_kind": plan.kind,
            "summary_label": plan.summary_label,
            "planner_reason": plan.reason,
            "focus_node_ids": plan.focus_node_ids,
            "focus_sources": plan.focus_sources,
            "focus_tags": plan.focus_tags,
            "focus_terms": plan.focus_terms,
            "supporting_node_ids": support_node_ids,
        }
        if existing is None:
            summary_node = await graph.add_node(
                content=content,
                node_type=NodeType.SUMMARY,
                tier=MemoryTier.SEMANTIC,
                importance=0.7,
                source="agent-maintenance",
                parent_node_ids=support_node_ids,
                tags=["maintenance", "collection-profile"],
                metadata=metadata,
                pinned=False,
            )
            summary_node.metadata["connection_index"] = build_summary_connection_index(
                summary_id=summary_node.id,
                summary_kind=plan.kind,
                source="agent-maintenance",
                content_hash=self._hash_text(content),
                entries=connection_entries,
            )
            await graph._storage.upsert_node(summary_node)
            await self._refresh_summary_links(graph, summary_node.id, support_node_ids)
            get_tracer().record_maintenance_summary_refresh(
                collection=collection,
                summary_label=plan.summary_label,
                supporting_node_count=len(support_node_ids),
                refreshed=False,
                planner_reason=plan.reason,
            )
            return summary_node.id

        existing.content = content
        existing.metadata.update(metadata)
        existing.metadata["connection_index"] = build_summary_connection_index(
            summary_id=existing.id,
            summary_kind=plan.kind,
            source="agent-maintenance",
            content_hash=self._hash_text(content),
            entries=connection_entries,
        )
        existing.importance = max(existing.importance, 0.7)
        existing.tier = MemoryTier.SEMANTIC
        existing.parent_node_ids = support_node_ids
        existing.tags = sorted(set(existing.tags) | {"maintenance", "collection-profile"})
        await graph.update_node(existing)
        await self._refresh_summary_links(graph, existing.id, support_node_ids)
        get_tracer().record_maintenance_summary_refresh(
            collection=collection,
            summary_label=plan.summary_label,
            supporting_node_count=len(support_node_ids),
            refreshed=True,
            planner_reason=plan.reason,
        )
        return existing.id

    async def _select_summary_support_nodes(
        self,
        collection: str,
        candidate_ids: list[str],
        limit: int = 4,
    ) -> list[str]:
        graph = self._graphs[collection]
        selected: list[str] = []
        seen: set[str] = set()
        for node_id in candidate_ids:
            if node_id in seen:
                continue
            seen.add(node_id)
            node = await graph.get_node(node_id)
            if node is None:
                continue
            if node.node_type == NodeType.SUMMARY and node.source == "agent-maintenance":
                continue
            if node.tier == MemoryTier.ARCHIVED:
                continue
            selected.append(node_id)
            if len(selected) >= limit:
                break
        return selected

    async def _upsert_reasoning_subnode(
        self,
        collection: str,
        parent_node_id: str,
        reasoning_trace: str,
        source_node_ids: list[str],
        question: str,
        label: str,
        confidence: float = 0.7,
    ) -> Optional[str]:
        """
        Create or update a REASONING sub-node linked to a parent answer node.

        Graph structure built:
          parent_node  --[INFERRED_FROM]-->  reasoning_node
          reasoning_node  --[INFERRED_FROM]-->  source_node  (×N)

        This makes the reasoning chain traversable: starting from any source
        node, following INFERRED_FROM edges (reversed) reaches the reasoning
        that used it, then the answer that was derived from that reasoning.

        Returns the reasoning node ID, or None if storage was skipped.
        """
        if not reasoning_trace or not reasoning_trace.strip():
            return None
        graph = self._graphs.get(collection)
        if graph is None:
            return None

        # Stable key — same question always reuses the same reasoning node
        import hashlib as _hashlib
        reasoning_key = _hashlib.sha1(
            f"reasoning:{question.strip().lower()}".encode()
        ).hexdigest()

        # Check if a reasoning node already exists for this question
        existing_reasoning: Optional[object] = None
        all_fact_nodes = await graph.list_nodes(node_type="fact", limit=10000)
        for node in all_fact_nodes:
            if (node.metadata or {}).get("reasoning_key") == reasoning_key:
                existing_reasoning = node
                break

        reasoning_content = f"[REASONING] {label}\n\n{reasoning_trace.strip()}"
        metadata = {
            "reasoning_key": reasoning_key,
            "question": question,
            "parent_node_id": parent_node_id,
            "source_node_ids": source_node_ids,
            "confidence": confidence,
        }

        if existing_reasoning is None:
            reasoning_node = await graph.add_node(
                content=reasoning_content,
                node_type=NodeType.FACT,
                tier=MemoryTier.SEMANTIC,
                importance=0.55,
                source="agent-reasoning",
                tags=["reasoning-trace", "traversal"],
                metadata=metadata,
            )
            reasoning_node_id = reasoning_node.id
        else:
            existing_reasoning.content = reasoning_content
            existing_reasoning.metadata.update(metadata)
            await graph.update_node(existing_reasoning)
            reasoning_node_id = existing_reasoning.id

        # parent_node --[INFERRED_FROM]--> reasoning_node
        # (answer was inferred by following this reasoning)
        existing_out = await graph.get_edges(parent_node_id, direction="out")
        already_linked = any(
            e.target_id == reasoning_node_id
            and e.relation_type == RelationType.INFERRED_FROM
            for e in existing_out
        )
        if not already_linked:
            await graph.add_edge(
                source_id=parent_node_id,
                target_id=reasoning_node_id,
                relation_type=RelationType.INFERRED_FROM,
                weight=confidence,
                confidence=confidence,
                created_by="agent",
                metadata={"kind": "answer_reasoning_provenance"},
            )

        # reasoning_node --[INFERRED_FROM]--> each source_node
        # (reasoning was derived from these source nodes)
        existing_reasoning_out = await graph.get_edges(reasoning_node_id, direction="out")
        already_sourced = {e.target_id for e in existing_reasoning_out
                          if e.relation_type == RelationType.INFERRED_FROM}
        for i, src_id in enumerate(source_node_ids[:8]):
            if src_id in already_sourced:
                continue
            await graph.add_edge(
                source_id=reasoning_node_id,
                target_id=src_id,
                relation_type=RelationType.INFERRED_FROM,
                weight=max(0.6, 1.0 - i * 0.05),
                confidence=confidence,
                created_by="agent",
                metadata={"kind": "reasoning_source", "source_rank": i + 1},
            )

        return reasoning_node_id

    async def _refresh_summary_links(
        self,
        graph: MemoryGraph,
        summary_node_id: str,
        support_node_ids: list[str],
    ) -> None:
        for edge in await graph.get_edges(summary_node_id, direction="out"):
            if edge.relation_type in {RelationType.SUMMARIZES, RelationType.REFERENCES}:
                await graph.delete_edge(edge.id)

        for index, node_id in enumerate(support_node_ids):
            await graph.add_edge(
                source_id=summary_node_id,
                target_id=node_id,
                relation_type=RelationType.SUMMARIZES,
                weight=max(0.7, 1.0 - (index * 0.08)),
                confidence=0.9,
                created_by="agent",
                metadata={"support_rank": index + 1, "kind": "maintenance_summary_support"},
            )

    def _collection_maintenance_fingerprint(self, nodes: list) -> str:
        pieces = []
        for node in nodes:
            if node.tier == MemoryTier.ARCHIVED:
                continue
            if node.node_type == NodeType.SUMMARY and node.source in {
                "agent-maintenance",
                "agent-reflection",
            }:
                continue
            pieces.append(f"{node.node_type.value}:{self._hash_text(node.content)}")
        joined = "|".join(sorted(pieces))
        return hashlib.sha1(joined.encode("utf-8")).hexdigest()

    @staticmethod
    def _hash_text(text: str) -> str:
        normalized = re.sub(r"\s+", " ", text or "").strip().lower()
        return hashlib.sha1(normalized.encode("utf-8")).hexdigest()

    def _pick_follow_up_query(
        self,
        *,
        original_question: str,
        current_query: str,
        suggested_query: Optional[str],
        nodes: list[Any],
        hop_index: int,
    ) -> str:
        """
        Ensure forced hops actually explore a new lead.

        If the model does not provide a useful next query, derive one from the
        most recently discovered sources so later hops do real exploration.
        """
        if suggested_query:
            cleaned = suggested_query.strip()
            if cleaned and cleaned.lower() != current_query.strip().lower():
                return cleaned

        recent_nodes = list(reversed(nodes[-8:]))

        source_names: list[str] = []
        excerpt_terms: list[str] = []
        for node in recent_nodes:
            source_name = node.source or (node.metadata or {}).get("filename") or (node.metadata or {}).get("source")
            if source_name:
                normalized_source = str(source_name).strip()
                if normalized_source and normalized_source not in source_names:
                    source_names.append(normalized_source)

            content = re.sub(r"\s+", " ", node.content or "").strip()
            if content:
                snippet = content.split(".")[0].split(":")[0].strip()
                if snippet and snippet.lower() != original_question.strip().lower():
                    excerpt_terms.append(snippet[:80])

        variants: list[str] = []
        for source_name in source_names[:3]:
            variants.append(f"{original_question} source:{source_name}")
        for snippet in excerpt_terms[:3]:
            variants.append(f"{original_question} {snippet}")
        variants.extend(
            [
                f"{original_question} example usage",
                f"{original_question} implementation details",
                f"{original_question} related methods",
            ]
        )

        for variant in variants:
            cleaned = re.sub(r"\s+", " ", variant).strip()
            if cleaned and cleaned.lower() != current_query.strip().lower():
                return cleaned

        return f"{original_question} follow-up {hop_index + 1}"

    async def stream_chat(
        self,
        collection: str,
        question: str,
        session_id: Optional[str] = None,
        top_k: int = 15,
        threshold: float = 0.25,
        depth: int = 2,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[dict]:
        """
        Streaming multi-turn chat.
        """
        self._assert_started()
        graph, agent, broker = await self._ensure_collection(collection)
        
        session = None
        history = []
        if session_id:
            session = self.sessions.get_session(session_id)
            history = session.get_history()

        # Step 1: Retrieval
        candidates = await graph.semantic_search_with_graph_expansion(
            query=question, top_k=top_k, threshold=threshold, depth=depth
        )
        
        # Step 2: Reasoning Stream
        full_answer = ""
        res_buffer = ""
        answer_started = False
        async for chunk in broker.reasoner.stream_reason(
            collection=collection,
            question=question,
            nodes=[c[0] for c in candidates[:broker.reasoner.config.max_context_nodes]],
            history=history,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            if chunk.get("type") == "metadata":
                res_buffer = chunk.get("raw_response", res_buffer)
                continue

            content = chunk.get("content", "")
            if not content:
                continue

            if chunk.get("type") == "answer":
                answer_started = True
                full_answer += content
                yield chunk
                continue

            # If the model is still emitting pre-answer reasoning, surface it
            # instead of making the client wait for a late final burst.
            if chunk.get("type") == "thinking" and not answer_started:
                yield {"type": "answer", "content": content}

        if not full_answer and res_buffer:
            parsed = broker.reasoner._parse_response(
                res_buffer,
                [c[0] for c in candidates[:broker.reasoner.config.max_context_nodes]],
                0.0,
            )
            full_answer = str(parsed.answer)
            yield {"type": "answer", "content": full_answer}

        # Step 3: Record history
        if session:
            session.add_message("user", question)
            session.add_message("assistant", full_answer)

    async def _run_dynamic_thinking(
        self,
        *,
        broker: ContextBroker,
        agent: MemoryAgent,
        collection: str,
        question: str,
        history: list[dict],
        thinking_steps: int = 2,
        hops_per_step: int = 4,
        min_hops_before_confidence: int = 4,
        confidence_threshold: float = 0.7,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> tuple[ReasoningResult, list[dict[str, Any]], list[Any], int]:
        """
        Run a bounded multi-hop reasoning loop.

        The model can keep adapting the next query at any time, but we only
        check confidence after a full thinking step of several hops.
        """
        accumulated_nodes: list[Any] = []
        seen_node_ids: set[str] = set()
        current_query = question
        last_reasoning: ReasoningResult | None = None
        step_summaries: list[dict[str, Any]] = []
        total_hops = 0

        for step_index in range(thinking_steps):
            step_hops = 0
            step_reasoning: ReasoningResult | None = None

            for _ in range(hops_per_step):
                total_hops += 1
                step_hops += 1

                nodes, _, _ = await broker.prepare_context(query=current_query)
                new_nodes = [n for n in nodes if n.id not in seen_node_ids]
                accumulated_nodes.extend(new_nodes)
                for node in new_nodes:
                    seen_node_ids.add(node.id)
                    agent.record_access(node.id)

                step_reasoning = await broker.reasoner.reason(
                    collection=collection,
                    question=question,
                    nodes=accumulated_nodes,
                    history=history,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                last_reasoning = step_reasoning

                if step_hops < min_hops_before_confidence:
                    current_query = self._pick_follow_up_query(
                        original_question=question,
                        current_query=current_query,
                        suggested_query=step_reasoning.suggested_query,
                        nodes=accumulated_nodes,
                        hop_index=step_hops,
                    )
                    continue

                if step_reasoning.is_complete or not step_reasoning.suggested_query:
                    break

                next_query = step_reasoning.suggested_query.strip()
                if not next_query or next_query.lower() == current_query.strip().lower():
                    break
                current_query = next_query

            if step_reasoning is None:
                break

            step_summaries.append(
                {
                    "step": step_index + 1,
                    "hops": step_hops,
                    "confidence": step_reasoning.confidence,
                    "complete": step_reasoning.is_complete,
                }
            )

            if step_reasoning.is_complete or step_reasoning.confidence >= confidence_threshold or not step_reasoning.suggested_query:
                break

            current_query = step_reasoning.suggested_query

        if last_reasoning is None:
            last_reasoning = await broker.reasoner.reason(
                collection=collection,
                question=question,
                nodes=accumulated_nodes,
                history=history,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        return last_reasoning, step_summaries, accumulated_nodes, total_hops

    async def recursive_chat(
        self,
        collection: str,
        question: str,
        session_id: Optional[str] = None,
        thinking_steps: int = 2,
        hops_per_step: int = 4,
        threshold: float = 0.7,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> ContextResponse:
        """
        Autonomous multi-hop reasoning (Thinking Mode).
        Continues searching in bounded thinking steps and checks confidence
        after each step.
        """
        self._assert_started()
        _, agent, broker = await self._ensure_collection(collection)
        
        history = []
        if session_id:
            history = self.sessions.get_session(session_id).get_history()
        last_reasoning, step_summaries, accumulated_nodes, total_hops = await self._run_dynamic_thinking(
            broker=broker,
            agent=agent,
            collection=collection,
            question=question,
            history=history,
            thinking_steps=thinking_steps,
            hops_per_step=hops_per_step,
            min_hops_before_confidence=4,
            confidence_threshold=threshold,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # Build final response
        response = ContextResponse(
            question=question,
            answer=last_reasoning.answer,
            reasoning_trace=(
                f"--- Thinking Status ---\n"
                f"Dynamic thinking completed in {len(step_summaries)} step(s) "
                f"across {total_hops} hop(s). Confidence was checked after each step.\n\n"
                f"--- Final Chain of Thought ---\n"
                f"{last_reasoning.reasoning_trace}"
            ),
            sources=[SourceNode.from_node(n, 1.0) for n in accumulated_nodes[:broker.reasoner.config.max_context_nodes]],
            total_nodes_searched=len({n.id for n in accumulated_nodes}),
            confidence=last_reasoning.confidence,
            retrieval_method=f"recursive(steps={len(step_summaries)}, hops={total_hops})",
            collection=collection,
            model_used=last_reasoning.model_used,
            latency_ms=0.0, # We'll compute this if needed
        )

        if session_id:
            s = self.sessions.get_session(session_id)
            s.add_message("user", question)
            s.add_message("assistant", str(response.answer))

        return response

    async def stream_recursive_chat(
        self,
        collection: str,
        question: str,
        session_id: Optional[str] = None,
        thinking_steps: int = 2,
        hops_per_step: int = 4,
        min_hops_before_confidence: int = 4,
        threshold: float = 0.7,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[dict]:
        """
        Streaming version of autonomous multi-hop reasoning.
        """
        self._assert_started()
        _, agent, broker = await self._ensure_collection(collection)
        
        history = []
        if session_id:
            history = self.sessions.get_session(session_id).get_history()
        accumulated_nodes: list[Any] = []
        seen_node_ids: set[str] = set()
        current_query = question
        last_reasoning: ReasoningResult | None = None
        last_query: Optional[str] = None
        last_new_nodes = 0
        low_progress_streak = 0

        for step_index in range(thinking_steps):
            step_hops = 0
            for hop_index in range(hops_per_step):
                step_hops += 1
                hop_plan = await broker.reasoner.plan_next_hop(
                    question=question,
                    current_query=current_query,
                    nodes=accumulated_nodes,
                    history=history,
                    prior_reasoning=last_reasoning.reasoning_trace if last_reasoning else None,
                    step_index=step_index,
                    thinking_steps=thinking_steps,
                    hop_index=hop_index,
                    hops_per_step=hops_per_step,
                    last_query=last_query,
                    last_new_nodes=last_new_nodes,
                    last_confidence=last_reasoning.confidence if last_reasoning else None,
                    low_progress_streak=low_progress_streak,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                active_query = hop_plan.query.strip() or current_query
                yield {
                    "type": "thinking",
                    "content": hop_plan.thought,
                }

                nodes, _, _ = await broker.prepare_context(query=active_query)
                new_nodes = [n for n in nodes if n.id not in seen_node_ids]
                accumulated_nodes.extend(new_nodes)
                for node in new_nodes:
                    seen_node_ids.add(node.id)
                    agent.record_access(node.id)
                last_query = active_query
                last_new_nodes = len(new_nodes)
                if last_new_nodes == 0:
                    low_progress_streak += 1
                else:
                    low_progress_streak = 0

                last_reasoning = await broker.reasoner.reason(
                    collection=collection,
                    question=question,
                    nodes=accumulated_nodes,
                    history=history,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                if step_hops < min_hops_before_confidence:
                    current_query = self._pick_follow_up_query(
                        original_question=question,
                        current_query=active_query,
                        suggested_query=last_reasoning.suggested_query,
                        nodes=accumulated_nodes,
                        hop_index=step_hops,
                    )
                    continue

                if last_reasoning.is_complete or not last_reasoning.suggested_query:
                    break

                next_query = last_reasoning.suggested_query.strip()
                if not next_query or next_query.lower() == active_query.strip().lower():
                    break
                current_query = next_query

            if last_reasoning is None:
                break

            if last_reasoning.is_complete or last_reasoning.confidence >= threshold or not last_reasoning.suggested_query:
                break

            current_query = last_reasoning.suggested_query

        if last_reasoning is None:
            last_reasoning = await broker.reasoner.reason(
                collection=collection,
                question=question,
                nodes=accumulated_nodes,
                history=history,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        yield {"type": "answer", "content": str(last_reasoning.answer)}

        if session_id:
            s = self.sessions.get_session(session_id)
            s.add_message("user", question)
            s.add_message("assistant", str(last_reasoning.answer))

    # ------------------------------------------------------------------ #
    # Agent / Admin                                                        #
    # ------------------------------------------------------------------ #

    async def trigger_agent_cycle(self, collection: str) -> dict:
        """
        Manually trigger an immediate agent cycle for a collection.
        Useful for testing or on-demand maintenance.
        """
        self._assert_started()
        _, agent, _ = await self._ensure_collection(collection)
        return await agent.run_cycle_now()

    async def get_agent_status(self, collection: str) -> dict:
        """Get the status of the collection's autonomous agent."""
        self._assert_started()
        _, agent, _ = await self._ensure_collection(collection)
        return agent.get_status()

    async def get_graph_stats(self, collection: str) -> dict:
        """Get high-level statistics about a collection's graph."""
        self._assert_started()
        graph, _, _ = await self._ensure_collection(collection)
        return await graph.get_stats()

    async def get_collection_stats(self, collection: str) -> dict:
        """Alias for get_graph_stats for ergonomic API."""
        return await self.get_graph_stats(collection)

    async def dedupe_collection(self, collection: str, dry_run: bool = False) -> dict:
        """
        Remove duplicate chunks from a collection.

        Two-pass strategy:
          1. Source-version dedup — if the same source file was ingested multiple
             times (different document_hash = different file versions), keep only
             the most recent ingestion and discard all older versions.
          2. Content-hash dedup — within the surviving set, if two nodes have
             identical content_hash (byte-for-byte same text), keep the one with
             higher importance (or the older node on a tie) and delete the rest.

        Returns a summary dict. When dry_run=True no nodes are deleted.
        """
        self._assert_started()
        graph, _, _ = await self._ensure_collection(collection)
        nodes = await graph.list_nodes(limit=200_000)

        to_delete: set[str] = set()

        # ── Pass 1: source-version dedup ─────────────────────────────────────
        # Group by source → document_hash → [nodes]
        by_source: dict[str, dict[str, list]] = {}
        for node in nodes:
            src = node.source
            doc_hash = (node.metadata or {}).get("document_hash")
            if not src or not doc_hash:
                continue
            by_source.setdefault(src, {}).setdefault(doc_hash, []).append(node)

        source_dupes = 0
        for src, versions in by_source.items():
            if len(versions) <= 1:
                continue
            # Sort versions by their latest ingested_at; keep the newest
            sorted_versions = sorted(
                versions.items(),
                key=lambda kv: max(
                    (n.metadata or {}).get("ingested_at", 0.0) for n in kv[1]
                ),
                reverse=True,
            )
            for _, stale_nodes in sorted_versions[1:]:
                for n in stale_nodes:
                    to_delete.add(n.id)
                    source_dupes += 1

        # ── Pass 2: content-hash dedup ────────────────────────────────────────
        # Among nodes not already marked for deletion, deduplicate identical text
        seen_content: dict[str, object] = {}  # content_hash → winning node
        content_dupes = 0
        for node in nodes:
            if node.id in to_delete:
                continue
            ch = (node.metadata or {}).get("content_hash") or self._hash_text(node.content or "")
            if not ch:
                continue
            if ch in seen_content:
                existing = seen_content[ch]
                # Keep higher importance; on tie keep the older node (lower created_at)
                if node.importance > existing.importance or (
                    node.importance == existing.importance
                    and node.created_at < existing.created_at
                ):
                    to_delete.add(existing.id)
                    seen_content[ch] = node
                else:
                    to_delete.add(node.id)
                content_dupes += 1
            else:
                seen_content[ch] = node

        deleted = 0
        if not dry_run:
            for node_id in to_delete:
                await graph.delete_node(node_id)
                deleted += 1

        return {
            "collection": collection,
            "scanned": len(nodes),
            "source_version_dupes": source_dupes,
            "content_hash_dupes": content_dupes,
            "total_duplicates": len(to_delete),
            "deleted": deleted,
            "remaining": len(nodes) - deleted,
            "dry_run": dry_run,
        }

    async def compact_storage(self) -> dict:
        """
        Rebuild the KuzuDB file from scratch to reclaim wasted disk space.

        KuzuDB pre-allocates buffer-pool-sized pages on first use (default:
        ~80 % of system RAM), which bloats the on-disk file to gigabytes even
        for tiny datasets.  This method:
          1. Stops all agents (they hold open connections).
          2. Calls KuzuBackend.compact() which exports data, recreates the
             file with a controlled 256 MB pool, and reimports everything.
          3. Restarts the agents.

        Safe to run at any time.  Returns a size-delta summary.
        """
        from stixdb.storage.kuzu_backend import KuzuBackend

        self._assert_started()
        if not isinstance(self._storage_backend, KuzuBackend):
            return {"error": "Storage compact is only supported for KuzuDB backends."}

        # Stop agents — they hold DB connections via their graphs
        for agent in list(self._agents.values()):
            await agent.stop()
        self._agents.clear()

        try:
            result = await self._storage_backend.compact()
        finally:
            # Restart agents for all currently-loaded collections
            for collection in list(self._graphs.keys()):
                graph = self._graphs[collection]
                agent = self._build_agent(collection, graph)
                self._agents[collection] = agent
                await agent.start()

        return result

    def get_traces(
        self,
        collection: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Retrieve agent thinking traces for observability / debugging."""
        return get_tracer().get_traces(collection=collection, event_type=event_type, limit=limit)

    # ------------------------------------------------------------------ #
    # Context manager support                                              #
    # ------------------------------------------------------------------ #

    async def __aenter__(self) -> "StixDBEngine":
        await self.start()
        return self

    async def __aexit__(self, *args) -> None:
        await self.stop()

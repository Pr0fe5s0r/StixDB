"""
Enricher — LLM bridge agent for semantic edge inference.

Responsibility: connect nodes that Pass 1 (AST) cannot connect.
Pass 1 wires code nodes to each other via structural facts (CALLS, IMPORTS, INHERITS).
The Enricher's job is to bridge the islands:

    code node  ──EXPLAINS──►  doc_section
    doc_section ──ABOUT──►    concept
    decision    ──DECIDES──►  function
    conversation ──CHAT──►   decision

Three triggers:
  1. Post-ingest   — called immediately after new nodes land in the graph.
                     Finds cross-type pairs with no semantic edge and enriches them.
  2. Background    — called by the worker on its cycle.
                     Processes the co-retrieval queue built up during searches.
  3. On-demand     — called via `stixdb enrich -c COLLECTION`.

Token efficiency:
  - Never scans the full collection blindly.
  - Post-ingest: guided by structural edges from Pass 1.
  - Background:  guided by co-retrieval patterns logged by the worker.
  - Skips any pair that already has a semantic edge between them.
  - Batches multiple pairs into one LLM call.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from stixdb.config import LLMProvider, ReasonerConfig
from stixdb.graph.edge import EdgeProvenance, RelationEdge, RelationType
from stixdb.graph.node import MemoryNode, NodeType

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────── #
# Constants                                                                     #
# ──────────────────────────────────────────────────────────────────────────── #

# Relation types that count as "semantic" — if one already exists between a pair
# we skip that pair (no double enrichment).
SEMANTIC_RELATION_TYPES: set[RelationType] = {
    RelationType.EXPLAINS,
    RelationType.MOTIVATES,
    RelationType.DECIDES,
    RelationType.IMPLEMENTS,
    RelationType.VALIDATES,
    RelationType.ABOUT,
    RelationType.SUPERSEDES,
    RelationType.CHAT,
    RelationType.INFERRED_FROM,
    RelationType.SIMILAR_TO,
    RelationType.CAUSES,
    RelationType.SUPPORTS,
    RelationType.CONTRADICTS,
}

# Confidence threshold below which we mark an edge AMBIGUOUS instead of INFERRED
AMBIGUOUS_THRESHOLD = 0.5

# Default batch size: pairs per LLM call
DEFAULT_BATCH_SIZE = 10

SYSTEM_PROMPT = """\
You are a knowledge graph enrichment agent. You receive pairs of nodes from a
knowledge graph and must identify the semantic relationship between them.

For each pair, choose ONE relation from this list (or "none" if no meaningful relation exists):
  explains    — node A clarifies, documents, or describes node B
  motivates   — node A is the reason or justification that node B exists
  decides     — node A (a decision) governs or constrains node B (code or design)
  implements  — node A (code) realises node B (a design decision or specification)
  validates   — node A (test or doc) confirms or verifies node B's behaviour
  about       — node A references or discusses node B (cross-media anchor)
  supersedes  — node A replaces or obsoletes node B
  none        — no meaningful semantic relationship exists

Rules:
1. Only return relations from the list above.
2. Confidence must be 0.0–1.0. Be conservative — prefer "none" over a weak guess.
3. Return a JSON array. One object per pair. No extra text.
4. Format: [{"pair_index": 0, "relation": "explains", "confidence": 0.85, "rationale": "..."}]
"""


# ──────────────────────────────────────────────────────────────────────────── #
# Data structures                                                               #
# ──────────────────────────────────────────────────────────────────────────── #

@dataclass
class NodePair:
    """A pair of nodes to be enriched."""
    source: MemoryNode
    target: MemoryNode
    trigger: str = "post_ingest"   # "post_ingest" | "background" | "on_demand"


@dataclass
class EnrichmentResult:
    edges_created: list[RelationEdge] = field(default_factory=list)
    pairs_skipped: int = 0          # already had a semantic edge
    pairs_no_relation: int = 0      # LLM returned "none"
    pairs_ambiguous: int = 0        # low confidence — marked AMBIGUOUS
    llm_calls: int = 0
    errors: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────── #
# Relation string -> enum                                                        #
# ──────────────────────────────────────────────────────────────────────────── #

_RELATION_MAP: dict[str, RelationType] = {
    "explains":   RelationType.EXPLAINS,
    "motivates":  RelationType.MOTIVATES,
    "decides":    RelationType.DECIDES,
    "implements": RelationType.IMPLEMENTS,
    "validates":  RelationType.VALIDATES,
    "about":      RelationType.ABOUT,
    "supersedes": RelationType.SUPERSEDES,
}


def _parse_relation(value: str) -> Optional[RelationType]:
    return _RELATION_MAP.get(value.strip().lower())


# ──────────────────────────────────────────────────────────────────────────── #
# Prompt builder                                                                #
# ──────────────────────────────────────────────────────────────────────────── #

def _build_enrichment_prompt(pairs: list[NodePair]) -> str:
    lines = [f"Classify the semantic relationship for each of the {len(pairs)} node pair(s) below.\n"]
    for i, pair in enumerate(pairs):
        src, tgt = pair.source, pair.target
        lines.append(f"--- Pair {i} ---")
        lines.append(f"Node A  type={src.node_type.value}  content={src.content[:200]}")
        if src.metadata.get("name"):
            lines.append(f"        name={src.metadata['name']}")
        if src.metadata.get("path"):
            lines.append(f"        path={src.metadata['path']}")
        lines.append(f"Node B  type={tgt.node_type.value}  content={tgt.content[:200]}")
        if tgt.metadata.get("name"):
            lines.append(f"        name={tgt.metadata['name']}")
        if tgt.metadata.get("path"):
            lines.append(f"        path={tgt.metadata['path']}")
        lines.append("")
    lines.append('Return a JSON array with one object per pair: [{"pair_index": 0, "relation": "...", "confidence": 0.0, "rationale": "..."}]')
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────── #
# LLM client (mirrors reasoner.py pattern)                                      #
# ──────────────────────────────────────────────────────────────────────────── #

async def _call_llm(prompt: str, config: ReasonerConfig) -> str:
    provider = config.provider

    if provider in (LLMProvider.OPENAI, LLMProvider.CUSTOM):
        import openai
        api_key = (
            config.openai_api_key if provider == LLMProvider.OPENAI
            else (config.custom_api_key or "dummy-key")
        )
        base_url = None if provider == LLMProvider.OPENAI else config.custom_base_url
        client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ]
        try:
            response = await client.chat.completions.create(
                model=config.model,
                messages=messages,
                temperature=0.1,
                max_tokens=2048,
                response_format={"type": "json_object"},
                timeout=config.timeout_seconds,
            )
            content = response.choices[0].message.content or ""
            if content.strip():
                return content
        except Exception:
            pass
        # Retry without json_object mode
        response = await client.chat.completions.create(
            model=config.model,
            messages=messages,
            temperature=0.1,
            max_tokens=2048,
            timeout=config.timeout_seconds,
        )
        return response.choices[0].message.content or ""

    if provider == LLMProvider.ANTHROPIC:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key or "")
        response = await client.messages.create(
            model=config.model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text if response.content else ""

    if provider == LLMProvider.OLLAMA:
        import openai
        client = openai.AsyncOpenAI(
            api_key="ollama",
            base_url=config.ollama_base_url.rstrip("/") + "/v1",
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ]
        response = await client.chat.completions.create(
            model=config.model,
            messages=messages,
            temperature=0.1,
            max_tokens=2048,
            timeout=config.timeout_seconds,
        )
        return response.choices[0].message.content or ""

    return ""


# ──────────────────────────────────────────────────────────────────────────── #
# Response parser                                                               #
# ──────────────────────────────────────────────────────────────────────────── #

def _extract_json_array(raw: str) -> list[dict]:
    """Extract a JSON array from LLM output, tolerating markdown fences and wrapper objects."""
    text = raw.strip()
    # Strip markdown code fences
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [p for p in parsed if isinstance(p, dict)]
        if isinstance(parsed, dict):
            # Single result object
            if "pair_index" in parsed:
                return [parsed]
            # Any key whose value is a list of dicts
            for val in parsed.values():
                if isinstance(val, list) and val and isinstance(val[0], dict):
                    return val
    except json.JSONDecodeError:
        pass

    # Find first [...] block in the raw text
    match = re.search(r"\[.*?\]", text, re.DOTALL)
    if match:
        try:
            arr = json.loads(match.group())
            if isinstance(arr, list):
                return [p for p in arr if isinstance(p, dict)]
        except json.JSONDecodeError:
            pass

    # Find first {...} block (single result)
    match = re.search(r"\{.*?\}", text, re.DOTALL)
    if match:
        try:
            obj = json.loads(match.group())
            if isinstance(obj, dict) and "pair_index" in obj:
                return [obj]
        except json.JSONDecodeError:
            pass

    return []


# ──────────────────────────────────────────────────────────────────────────── #
# Pair filter                                                                   #
# ──────────────────────────────────────────────────────────────────────────── #

def filter_unenriched_pairs(
    pairs: list[NodePair],
    existing_edges: list[RelationEdge],
) -> list[NodePair]:
    """
    Remove pairs that already have a semantic edge in either direction.
    This is the primary token-efficiency guard.
    """
    semantic_pairs: set[tuple[str, str]] = set()
    for edge in existing_edges:
        if edge.relation_type in SEMANTIC_RELATION_TYPES:
            semantic_pairs.add((edge.source_id, edge.target_id))
            semantic_pairs.add((edge.target_id, edge.source_id))  # undirected check

    return [
        p for p in pairs
        if (p.source.id, p.target.id) not in semantic_pairs
    ]


# ──────────────────────────────────────────────────────────────────────────── #
# Pair discovery helpers                                                        #
# ──────────────────────────────────────────────────────────────────────────── #

# Node types that Pass 1 cannot connect structurally — these are the bridge candidates
_NON_CODE_TYPES: set[NodeType] = {
    NodeType.DOC_FILE,
    NodeType.DOC_SECTION,
    NodeType.DECISION,
    NodeType.CONVERSATION,
    NodeType.CONCEPT,
    NodeType.FACT,
    NodeType.ENTITY,
    NodeType.SUMMARY,
}

_CODE_TYPES: set[NodeType] = {
    NodeType.CODE_FILE,
    NodeType.MODULE,
    NodeType.FUNCTION,
    NodeType.CLASS,
}


def _is_bridge_candidate(node: MemoryNode) -> bool:
    """
    A non-code node is a bridge candidate if it is a rich semantic node
    (DOC_FILE, DOC_SECTION, DECISION, CONVERSATION, CONCEPT) or an explicitly
    user-stored FACT/ENTITY (pinned=True).

    Auto-chunked text from ingest is pinned=False and excluded — those are
    search targets, not graph bridge candidates.
    """
    if node.node_type in (
        NodeType.DOC_FILE, NodeType.DOC_SECTION,
        NodeType.DECISION, NodeType.CONVERSATION, NodeType.CONCEPT,
    ):
        return True
    if node.node_type in (NodeType.FACT, NodeType.ENTITY) and node.pinned:
        return True
    return False


def find_cross_type_pairs(
    new_nodes: list[MemoryNode],
    existing_nodes: list[MemoryNode],
) -> list[NodePair]:
    """
    Find pairs that cross the code/non-code boundary.
    These are the pairs Pass 1 cannot connect — prime enrichment candidates.
    """
    pairs: list[NodePair] = []
    new_code = [n for n in new_nodes if n.node_type in _CODE_TYPES]
    new_non_code = [n for n in new_nodes if _is_bridge_candidate(n)]
    existing_code = [n for n in existing_nodes if n.node_type in _CODE_TYPES]
    existing_non_code = [n for n in existing_nodes if _is_bridge_candidate(n)]

    # New code nodes ↔ all existing non-code nodes
    for code_node in new_code:
        for non_code_node in existing_non_code:
            pairs.append(NodePair(source=code_node, target=non_code_node, trigger="post_ingest"))

    # New non-code nodes ↔ all existing code nodes
    for non_code_node in new_non_code:
        for code_node in existing_code:
            pairs.append(NodePair(source=non_code_node, target=code_node, trigger="post_ingest"))

    # New non-code ↔ new non-code (decisions linking to docs, etc.)
    for i, a in enumerate(new_non_code):
        for b in new_non_code[i + 1:]:
            pairs.append(NodePair(source=a, target=b, trigger="post_ingest"))

    return pairs


# ──────────────────────────────────────────────────────────────────────────── #
# Enricher                                                                      #
# ──────────────────────────────────────────────────────────────────────────── #

class Enricher:
    """
    LLM enrichment agent.

    Usage:
        enricher = Enricher(config=reasoner_config, collection="proj_myapp")

        # Post-ingest trigger
        result = await enricher.enrich_post_ingest(new_nodes, existing_nodes, existing_edges)

        # Background trigger (co-retrieval queue)
        result = await enricher.enrich_pairs(pairs, existing_edges)
    """

    def __init__(
        self,
        config: ReasonerConfig,
        collection: str,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self.config = config
        self.collection = collection
        self.batch_size = batch_size

    async def enrich_post_ingest(
        self,
        new_nodes: list[MemoryNode],
        existing_nodes: list[MemoryNode],
        existing_edges: list[RelationEdge],
    ) -> EnrichmentResult:
        """
        Trigger 1 — called immediately after new nodes are added to the graph.
        Finds cross-type pairs and enriches unannotated ones.
        """
        if self.config.provider == LLMProvider.NONE:
            return EnrichmentResult()

        pairs = find_cross_type_pairs(new_nodes, existing_nodes)
        return await self.enrich_pairs(pairs, existing_edges)

    async def enrich_pairs(
        self,
        pairs: list[NodePair],
        existing_edges: list[RelationEdge],
    ) -> EnrichmentResult:
        """
        Core enrichment loop. Filters, batches, calls LLM, returns new edges.

        Trigger 2 (background co-retrieval) and Trigger 3 (on-demand) both call this.
        """
        result = EnrichmentResult()

        if self.config.provider == LLMProvider.NONE or not pairs:
            return result

        # Filter out pairs that already have a semantic edge
        unenriched = filter_unenriched_pairs(pairs, existing_edges)
        result.pairs_skipped = len(pairs) - len(unenriched)

        if not unenriched:
            logger.debug("Enricher: all %d pairs already have semantic edges — skipping", len(pairs))
            return result

        logger.info(
            "Enricher: %d pairs to enrich (%d skipped — already annotated)",
            len(unenriched), result.pairs_skipped,
        )

        # Process in batches
        for batch_start in range(0, len(unenriched), self.batch_size):
            batch = unenriched[batch_start : batch_start + self.batch_size]
            await self._process_batch(batch, result)

        logger.info(
            "Enricher done: %d edges created, %d ambiguous, %d no-relation, %d errors",
            len(result.edges_created),
            result.pairs_ambiguous,
            result.pairs_no_relation,
            len(result.errors),
        )
        return result

    async def enrich_pairs_stream(
        self,
        pairs: list[NodePair],
        existing_edges: list[RelationEdge],
    ):
        """
        Like enrich_pairs() but yields a progress dict after each batch so the
        caller can stream it to a client.  Does NOT persist edges — the caller
        must do that using the edge objects in the final "done" event.

        Yields dicts:
            {"type": "start",    "total_pairs": N, "total_batches": N}
            {"type": "batch",    "batch": N, "total_batches": N,
             "edges_this_batch": [...], "edges_so_far": N,
             "no_relation": N, "errors": [...]}
            {"type": "done",     "edges_created": [...RelationEdge...],
             "pairs_skipped": N, "pairs_no_relation": N,
             "pairs_ambiguous": N, "llm_calls": N, "errors": [...]}
        """
        result = EnrichmentResult()

        if self.config.provider == LLMProvider.NONE or not pairs:
            yield {"type": "done", "edges_created": [], "pairs_skipped": 0,
                   "pairs_no_relation": 0, "pairs_ambiguous": 0, "llm_calls": 0, "errors": []}
            return

        unenriched = filter_unenriched_pairs(pairs, existing_edges)
        result.pairs_skipped = len(pairs) - len(unenriched)

        total_batches = max(1, -(-len(unenriched) // self.batch_size))  # ceil
        yield {"type": "start", "total_pairs": len(unenriched), "total_batches": total_batches,
               "pairs_skipped": result.pairs_skipped}

        batch_num = 0
        for batch_start in range(0, len(unenriched), self.batch_size):
            batch_num += 1
            batch = unenriched[batch_start : batch_start + self.batch_size]
            edges_before = len(result.edges_created)
            await self._process_batch(batch, result)
            new_edges = result.edges_created[edges_before:]
            yield {
                "type": "batch",
                "batch": batch_num,
                "total_batches": total_batches,
                "edges_this_batch": len(new_edges),
                "edges_so_far": len(result.edges_created),
                "no_relation": result.pairs_no_relation,
                "ambiguous": result.pairs_ambiguous,
                "errors": result.errors[len(result.errors) - (result.llm_calls - batch_num + 1):] if result.errors else [],
            }

        yield {
            "type": "done",
            "edges_created": result.edges_created,
            "pairs_skipped": result.pairs_skipped,
            "pairs_no_relation": result.pairs_no_relation,
            "pairs_ambiguous": result.pairs_ambiguous,
            "llm_calls": result.llm_calls,
            "errors": result.errors,
        }

    async def _process_batch(
        self,
        batch: list[NodePair],
        result: EnrichmentResult,
    ) -> None:
        prompt = _build_enrichment_prompt(batch)
        try:
            raw = await _call_llm(prompt, self.config)
            result.llm_calls += 1
        except Exception as exc:
            error_msg = f"LLM call failed: {exc}"
            logger.warning("Enricher: %s", error_msg)
            result.errors.append(error_msg)
            return

        items = _extract_json_array(raw)
        if not items:
            logger.warning("Enricher: LLM returned unparseable response for batch of %d", len(batch))
            result.errors.append(f"Unparseable LLM response: {raw[:200]}")
            return

        for item in items:
            pair_index = item.get("pair_index")
            if pair_index is None or pair_index >= len(batch):
                continue

            pair = batch[pair_index]
            relation_str = item.get("relation", "none")
            confidence = float(item.get("confidence", 0.0))
            rationale = item.get("rationale", "")

            if relation_str == "none" or confidence == 0.0:
                result.pairs_no_relation += 1
                continue

            relation_type = _parse_relation(relation_str)
            if relation_type is None:
                result.pairs_no_relation += 1
                continue

            provenance = (
                EdgeProvenance.AMBIGUOUS if confidence < AMBIGUOUS_THRESHOLD
                else EdgeProvenance.INFERRED
            )
            if provenance == EdgeProvenance.AMBIGUOUS:
                result.pairs_ambiguous += 1

            edge = RelationEdge(
                collection=self.collection,
                source_id=pair.source.id,
                target_id=pair.target.id,
                relation_type=relation_type,
                weight=confidence,
                confidence=confidence,
                provenance=provenance,
                rationale=rationale or None,
                created_by="enricher",
                metadata={
                    "trigger": pair.trigger,
                    "source_type": pair.source.node_type.value,
                    "target_type": pair.target.node_type.value,
                },
            )
            result.edges_created.append(edge)

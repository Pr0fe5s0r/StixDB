"""
Memory Search API routes.

POST /search  — product-style search across one or more StixDB collections
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from stixdb.engine import StixDBEngine

router = APIRouter()


def _recency_score(last_accessed: float | None, now: float) -> float:
    if not last_accessed:
        return 0.0
    elapsed_hours = max(0.0, (now - last_accessed) / 3600.0)
    return 2.0 ** (-elapsed_hours / 12.0)


def _frequency_score(access_count: int | None) -> float:
    if not access_count:
        return 0.0
    return min(1.0, float(access_count) / 10.0)


def _tier_boost(tier: str | None) -> float:
    boosts = {
        "working": 1.0,
        "episodic": 0.75,
        "semantic": 0.55,
        "procedural": 0.5,
        "archived": 0.2,
    }
    return boosts.get(str(tier or "").lower(), 0.4)


def _temperature_label(heat_score: float) -> str:
    if heat_score >= 0.75:
        return "hot"
    if heat_score >= 0.45:
        return "warm"
    return "cold"


def _build_heatmap(node: dict[str, Any]) -> dict[str, Any]:
    now = time.time()
    access_count = int(node.get("access_count") or 0)
    last_accessed = node.get("last_accessed")
    importance = float(node.get("importance") or 0.0)
    decay_score = float(node.get("decay_score") or 0.0)
    recency = _recency_score(last_accessed, now)
    frequency = _frequency_score(access_count)
    tier_score = _tier_boost(node.get("tier"))
    heat_score = (
        0.35 * frequency
        + 0.30 * recency
        + 0.20 * decay_score
        + 0.10 * importance
        + 0.05 * tier_score
    )
    age_hours = None
    if last_accessed:
        age_hours = round(max(0.0, (now - float(last_accessed)) / 3600.0), 3)
    return {
        "heat_score": round(heat_score, 6),
        "temperature": _temperature_label(heat_score),
        "access_count": access_count,
        "recency_score": round(recency, 6),
        "frequency_score": round(frequency, 6),
        "decay_score": round(decay_score, 6),
        "importance_score": round(importance, 6),
        "tier_score": round(tier_score, 6),
        "last_accessed_age_hours": age_hours,
    }


def _source_name(node: dict[str, Any]) -> str:
    metadata = node.get("metadata") or {}
    return (
        node.get("source")
        or metadata.get("source")
        or metadata.get("filepath")
        or metadata.get("file_path")
        or "unknown"
    )


def _title_for_result(node: dict[str, Any]) -> str:
    metadata = node.get("metadata") or {}
    explicit_title = metadata.get("title") or metadata.get("name")
    if explicit_title:
        return str(explicit_title)

    source_name = _source_name(node)
    if source_name != "unknown":
        return str(source_name)

    content = str(node.get("content", "")).strip()
    if not content:
        return "Untitled memory"

    first_line = content.splitlines()[0].strip()
    if len(first_line) <= 80:
        return first_line
    return first_line[:77] + "..."


def _truncate_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _matches_source_filter(source_name: str, source_filter: list[str]) -> bool:
    if not source_filter:
        return True

    allow = [item.lower() for item in source_filter if not item.startswith("-")]
    deny = [item[1:].lower() for item in source_filter if item.startswith("-")]

    if allow and deny:
        raise HTTPException(
            status_code=400,
            detail="source_filter must use either allowlist or denylist mode, not both.",
        )

    source_name_lc = source_name.lower()
    if allow:
        return any(term in source_name_lc for term in allow)
    return not any(term in source_name_lc for term in deny)


def _matches_tags(node_tags: list[str], required_tags: list[str]) -> bool:
    if not required_tags:
        return True
    node_tags_lc = {tag.lower() for tag in node_tags}
    return any(tag.lower() in node_tags_lc for tag in required_tags)


def _to_search_result(
    collection: str,
    node: dict[str, Any],
    max_chars_per_result: int,
    include_metadata: bool,
    include_heatmap: bool,
) -> dict[str, Any]:
    source_name = _source_name(node)
    snippet = _truncate_text(str(node.get("content", "")), max_chars_per_result)
    metadata = node.get("metadata") or {}
    result = {
        "title": _title_for_result(node),
        "source": source_name,
        "collection": collection,
        "node_id": node["id"],
        "snippet": snippet,
        "score": round(float(node.get("score", 0.0)), 6),
        "node_type": node.get("node_type"),
        "tier": node.get("tier"),
        "importance": node.get("importance"),
        "tags": node.get("tags", []),
        "created_at": node.get("created_at"),
        "last_accessed": node.get("last_accessed"),
        "metadata": metadata if include_metadata else {},
    }
    if include_heatmap:
        result["heatmap"] = _build_heatmap(node)
    return result


class SearchRequest(BaseModel):
    query: str | list[str] = Field(
        ...,
        description="A single search query or up to 5 queries for batch search.",
    )
    collection: str | None = Field(
        default=None,
        description="Search a single collection.",
    )
    collections: list[str] = Field(
        default_factory=list,
        description="Search across multiple collections.",
    )
    max_results: int = Field(
        default=10,
        ge=1,
        le=20,
        description="Maximum results to return per query.",
    )
    top_k: int = Field(
        default=25,
        ge=1,
        le=100,
        description="Retrieval fan-out before filtering and ranking.",
    )
    threshold: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Minimum semantic similarity threshold.",
    )
    depth: int = Field(
        default=1,
        ge=0,
        le=4,
        description="Graph expansion depth from seed matches.",
    )
    source_filter: list[str] = Field(
        default_factory=list,
        description="Allowlist or denylist of source names. Prefix entries with '-' for denylist mode.",
    )
    tag_filter: list[str] = Field(
        default_factory=list,
        description="Return results matching any of these tags.",
    )
    node_type_filter: list[str] = Field(
        default_factory=list,
        description="Optional filter for node types.",
    )
    tier_filter: list[str] = Field(
        default_factory=list,
        description="Optional filter for memory tiers.",
    )
    max_chars_per_result: int = Field(
        default=1200,
        ge=100,
        le=20000,
        description="Maximum snippet length per result.",
    )
    include_metadata: bool = Field(
        default=True,
        description="Include stored metadata in each result.",
    )
    include_heatmap: bool = Field(
        default=False,
        description="Include memory heatmap metrics for each result.",
    )
    sort_by: str = Field(
        default="relevance",
        description="Sort results by relevance, heat, or hybrid.",
    )

    @model_validator(mode="after")
    def validate_request(self) -> "SearchRequest":
        if isinstance(self.query, list) and len(self.query) > 5:
            raise ValueError("query accepts at most 5 items for multi-query search.")

        selected_collections = set(self.collections)
        if self.collection:
            selected_collections.add(self.collection)
        if not selected_collections:
            raise ValueError("Provide collection or collections.")

        if len(self.source_filter) > 20:
            raise ValueError("source_filter accepts at most 20 entries.")

        if self.sort_by not in {"relevance", "heat", "hybrid"}:
            raise ValueError("sort_by must be one of: relevance, heat, hybrid.")

        return self


async def _search_collection(
    engine: StixDBEngine,
    collection: str,
    query: str,
    top_k: int,
    threshold: float,
    depth: int,
) -> list[dict[str, Any]]:
    results = await engine.retrieve(
        collection=collection,
        query=query,
        top_k=top_k,
        threshold=threshold,
        depth=depth,
    )
    return results


def _filter_and_rank_results(
    collection: str,
    nodes: list[dict[str, Any]],
    source_filter: list[str],
    tag_filter: list[str],
    node_type_filter: list[str],
    tier_filter: list[str],
    max_chars_per_result: int,
    include_metadata: bool,
    include_heatmap: bool,
    sort_by: str,
) -> list[dict[str, Any]]:
    node_type_set = {value.lower() for value in node_type_filter}
    tier_set = {value.lower() for value in tier_filter}

    filtered: list[dict[str, Any]] = []
    for node in nodes:
        source_name = _source_name(node)
        if not _matches_source_filter(source_name, source_filter):
            continue
        if node_type_set and str(node.get("node_type", "")).lower() not in node_type_set:
            continue
        if tier_set and str(node.get("tier", "")).lower() not in tier_set:
            continue
        if not _matches_tags(node.get("tags", []), tag_filter):
            continue
        filtered.append(
            _to_search_result(
                collection=collection,
                node=node,
                max_chars_per_result=max_chars_per_result,
                include_metadata=include_metadata,
                include_heatmap=include_heatmap,
            )
        )

    if sort_by == "heat":
        filtered.sort(
            key=lambda item: item.get("heatmap", {}).get("heat_score", 0.0),
            reverse=True,
        )
    elif sort_by == "hybrid":
        filtered.sort(
            key=lambda item: (
                0.65 * item["score"]
                + 0.35 * item.get("heatmap", {}).get("heat_score", 0.0)
            ),
            reverse=True,
        )
    else:
        filtered.sort(key=lambda item: item["score"], reverse=True)
    return filtered


@router.post("/search")
async def search(body: SearchRequest, request: Request):
    """
    Search one or more StixDB collections and return ranked memory results.

    This endpoint is designed as a product-style Search API for memory systems:
    one or more queries in, structured ranked results out.
    """
    engine: StixDBEngine = request.app.state.engine

    target_collections = list(dict.fromkeys(([body.collection] if body.collection else []) + body.collections))
    queries = body.query if isinstance(body.query, list) else [body.query]

    query_results: list[dict[str, Any]] = []
    for query_text in queries:
        merged_results: list[dict[str, Any]] = []
        searched_collections: list[str] = []

        for collection in target_collections:
            collection_results = await _search_collection(
                engine=engine,
                collection=collection,
                query=query_text,
                top_k=body.top_k,
                threshold=body.threshold,
                depth=body.depth,
            )
            filtered_results = _filter_and_rank_results(
                collection=collection,
                nodes=collection_results,
                source_filter=body.source_filter,
                tag_filter=body.tag_filter,
                node_type_filter=body.node_type_filter,
                tier_filter=body.tier_filter,
                max_chars_per_result=body.max_chars_per_result,
                include_metadata=body.include_metadata,
                include_heatmap=body.include_heatmap or body.sort_by in {"heat", "hybrid"},
                sort_by=body.sort_by,
            )
            merged_results.extend(filtered_results)
            searched_collections.append(collection)

        if body.sort_by == "heat":
            merged_results.sort(
                key=lambda item: item.get("heatmap", {}).get("heat_score", 0.0),
                reverse=True,
            )
        elif body.sort_by == "hybrid":
            merged_results.sort(
                key=lambda item: (
                    0.65 * item["score"]
                    + 0.35 * item.get("heatmap", {}).get("heat_score", 0.0)
                ),
                reverse=True,
            )
        else:
            merged_results.sort(key=lambda item: item["score"], reverse=True)
        merged_results = merged_results[: body.max_results]

        query_results.append(
            {
                "query": query_text,
                "collections": searched_collections,
                "results": merged_results,
            }
        )

    response: dict[str, Any] = {"id": str(uuid.uuid4())}
    if isinstance(body.query, list):
        response["results"] = query_results
    else:
        response["query"] = queries[0]
        response["collections"] = target_collections
        response["results"] = query_results[0]["results"] if query_results else []

    response["search_mode"] = "multi_query" if isinstance(body.query, list) else "single_query"
    response["max_results"] = body.max_results
    response["sort_by"] = body.sort_by
    response["include_heatmap"] = body.include_heatmap or body.sort_by in {"heat", "hybrid"}
    return response

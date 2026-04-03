from __future__ import annotations

from typing import Any
from .base import _BaseResource, _AsyncBaseResource


class SearchAPI(_BaseResource):
    def create(
        self,
        query: str | list[str],
        *,
        collection: str | None = None,
        collections: list[str] | None = None,
        max_results: int = 10,
        top_k: int = 25,
        threshold: float = 0.25,
        depth: int = 1,
        source_filter: list[str] | None = None,
        tag_filter: list[str] | None = None,
        node_type_filter: list[str] | None = None,
        tier_filter: list[str] | None = None,
        max_chars_per_result: int = 1200,
        include_metadata: bool = True,
        include_heatmap: bool = False,
        sort_by: str = "relevance",
    ) -> dict[str, Any]:
        return self._client._request(
            "POST",
            "/search",
            json={
                "query": query,
                "collection": collection,
                "collections": collections or [],
                "max_results": max_results,
                "top_k": top_k,
                "threshold": threshold,
                "depth": depth,
                "source_filter": source_filter or [],
                "tag_filter": tag_filter or [],
                "node_type_filter": node_type_filter or [],
                "tier_filter": tier_filter or [],
                "max_chars_per_result": max_chars_per_result,
                "include_metadata": include_metadata,
                "include_heatmap": include_heatmap,
                "sort_by": sort_by,
            },
        )


class AsyncSearchAPI(_AsyncBaseResource):
    async def create(
        self,
        query: str | list[str],
        *,
        collection: str | None = None,
        collections: list[str] | None = None,
        max_results: int = 10,
        top_k: int = 25,
        threshold: float = 0.25,
        depth: int = 1,
        source_filter: list[str] | None = None,
        tag_filter: list[str] | None = None,
        node_type_filter: list[str] | None = None,
        tier_filter: list[str] | None = None,
        max_chars_per_result: int = 1200,
        include_metadata: bool = True,
        include_heatmap: bool = False,
        sort_by: str = "relevance",
    ) -> dict[str, Any]:
        return await self._client._request(
            "POST",
            "/search",
            json={
                "query": query,
                "collection": collection,
                "collections": collections or [],
                "max_results": max_results,
                "top_k": top_k,
                "threshold": threshold,
                "depth": depth,
                "source_filter": source_filter or [],
                "tag_filter": tag_filter or [],
                "node_type_filter": node_type_filter or [],
                "tier_filter": tier_filter or [],
                "max_chars_per_result": max_chars_per_result,
                "include_metadata": include_metadata,
                "include_heatmap": include_heatmap,
                "sort_by": sort_by,
            },
        )

from __future__ import annotations

from typing import Any
from .base import _BaseResource, _AsyncBaseResource


class QueryAPI(_BaseResource):
    def ask(
        self,
        collection: str,
        *,
        question: str,
        top_k: int = 15,
        threshold: float = 0.25,
        depth: int = 2,
        system_prompt: str | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._client._request(
            "POST",
            f"/collections/{collection}/ask",
            json={
                "question": question,
                "top_k": top_k,
                "threshold": threshold,
                "depth": depth,
                "system_prompt": system_prompt,
                "output_schema": output_schema,
            },
        )

    def retrieve(
        self,
        collection: str,
        *,
        query: str,
        top_k: int = 10,
        threshold: float = 0.25,
        depth: int = 1,
    ) -> dict[str, Any]:
        return self._client._request(
            "POST",
            f"/collections/{collection}/retrieve",
            json={
                "query": query,
                "top_k": top_k,
                "threshold": threshold,
                "depth": depth,
            },
        )


class AsyncQueryAPI(_AsyncBaseResource):
    async def ask(
        self,
        collection: str,
        *,
        question: str,
        top_k: int = 15,
        threshold: float = 0.25,
        depth: int = 2,
        system_prompt: str | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._client._request(
            "POST",
            f"/collections/{collection}/ask",
            json={
                "question": question,
                "top_k": top_k,
                "threshold": threshold,
                "depth": depth,
                "system_prompt": system_prompt,
                "output_schema": output_schema,
            },
        )

    async def retrieve(
        self,
        collection: str,
        *,
        query: str,
        top_k: int = 10,
        threshold: float = 0.25,
        depth: int = 1,
    ) -> dict[str, Any]:
        return await self._client._request(
            "POST",
            f"/collections/{collection}/retrieve",
            json={
                "query": query,
                "top_k": top_k,
                "threshold": threshold,
                "depth": depth,
            },
        )

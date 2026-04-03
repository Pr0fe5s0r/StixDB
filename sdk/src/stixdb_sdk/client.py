from __future__ import annotations

from typing import Any
import httpx

from .search import SearchAPI, AsyncSearchAPI
from .memory import MemoryAPI, AsyncMemoryAPI
from .query import QueryAPI, AsyncQueryAPI


class StixDBClient:
    def __init__(
        self,
        *,
        base_url: str = "http://localhost:4020",
        api_key: str | None = None,
        timeout: float = 60.0,
        headers: dict[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        request_headers = dict(headers or {})
        if api_key:
            request_headers.setdefault("Authorization", f"Bearer {api_key}")

        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers=request_headers,
            transport=transport,
        )
        self.search = SearchAPI(self)
        self.memory = MemoryAPI(self)
        self.query = QueryAPI(self)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self._client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> StixDBClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


class AsyncStixDBClient:
    def __init__(
        self,
        *,
        base_url: str = "http://localhost:4020",
        api_key: str | None = None,
        timeout: float = 60.0,
        headers: dict[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        request_headers = dict(headers or {})
        if api_key:
            request_headers.setdefault("Authorization", f"Bearer {api_key}")

        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers=request_headers,
            transport=transport,
        )
        self.search = AsyncSearchAPI(self)
        self.memory = AsyncMemoryAPI(self)
        self.query = AsyncQueryAPI(self)

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = await self._client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/health")

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> AsyncStixDBClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

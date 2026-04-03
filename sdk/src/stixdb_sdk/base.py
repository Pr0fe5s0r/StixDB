from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client import StixDBClient, AsyncStixDBClient


class _BaseResource:
    def __init__(self, client: StixDBClient) -> None:
        self._client = client


class _AsyncBaseResource:
    def __init__(self, client: AsyncStixDBClient) -> None:
        self._client = client

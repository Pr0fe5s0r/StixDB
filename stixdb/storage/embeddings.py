"""
Embedding clients for StixDB.

Provides an instance-based client for embeddings instead of a global singleton.
Supports SentenceTransformers, OpenAI, and Ollama.
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

import numpy as np

from stixdb.config import EmbeddingConfig, EmbeddingProvider


class EmbeddingClient:
    """Base interface for embedding text."""

    async def embed_text(self, text: str) -> np.ndarray:
        """Embed a single string. Returns a float32 numpy array."""
        raise NotImplementedError

    async def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        """Embed a batch of strings."""
        raise NotImplementedError

    async def close(self) -> None:
        """Cleanup any resources if needed."""
        pass


class SentenceTransformerClient(EmbeddingClient):
    """Local embeddings using sentence-transformers."""

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name)

    async def embed_text(self, text: str) -> np.ndarray:
        loop = asyncio.get_event_loop()
        vec = await loop.run_in_executor(None, lambda: self.model.encode(text, normalize_embeddings=True))
        return vec.astype(np.float32)

    async def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        if not texts:
            return []
        loop = asyncio.get_event_loop()
        vecs = await loop.run_in_executor(
            None, lambda: self.model.encode(texts, normalize_embeddings=True, batch_size=64)
        )
        return [v.astype(np.float32) for v in vecs]


class OpenAIEmbeddingClient(EmbeddingClient):
    """Embeddings using OpenAI API or compatible custom endpoints."""

    def __init__(self, api_key: str, model_name: str, base_url: Optional[str] = None) -> None:
        import openai
        
        # Determine actual API key
        resolved_key = api_key
        if base_url and (not api_key or api_key.strip() == ""):
            resolved_key = "dummy-key" # Avoid missing api key error if local
            
        self.client = openai.AsyncOpenAI(api_key=resolved_key, base_url=base_url)
        self.model = model_name

    async def embed_text(self, text: str) -> np.ndarray:
        response = await self.client.embeddings.create(input=[text], model=self.model)
        return np.array(response.data[0].embedding, dtype=np.float32)

    async def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        if not texts:
            return []
        # OpenAI max batch size is typically 2048 depending on the model
        response = await self.client.embeddings.create(input=texts, model=self.model)
        return [np.array(item.embedding, dtype=np.float32) for item in response.data]


class OllamaEmbeddingClient(EmbeddingClient):
    """Embeddings using Ollama REST API."""

    def __init__(self, base_url: str, model_name: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model_name

    async def embed_text(self, text: str) -> np.ndarray:
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text}
            )
            response.raise_for_status()
            data = response.json()
            return np.array(data["embedding"], dtype=np.float32)

    async def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        # Ollama /api/embeddings endpoint historically only supports a single prompt
        # We process them concurrently.
        if not texts:
            return []
        import httpx
        async with httpx.AsyncClient() as client:
            async def _embed(t: str) -> np.ndarray:
                response = await client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model, "prompt": t}
                )
                response.raise_for_status()
                data = response.json()
                return np.array(data["embedding"], dtype=np.float32)
            
            vecs = await asyncio.gather(*[_embed(t) for t in texts])
            return list(vecs)


def build_embedding_client(config: EmbeddingConfig) -> EmbeddingClient:
    if config.provider == EmbeddingProvider.SENTENCE_TRANSFORMERS:
        return SentenceTransformerClient(config.model)
    elif config.provider == EmbeddingProvider.OPENAI:
        if not config.openai_api_key:
            raise ValueError("openai_api_key is required for OpenAI embeddings")
        return OpenAIEmbeddingClient(config.openai_api_key, config.model)
    elif config.provider == EmbeddingProvider.OLLAMA:
        return OllamaEmbeddingClient(config.ollama_base_url, config.model)
    elif config.provider == EmbeddingProvider.CUSTOM:
        key = config.custom_api_key or "dummy-key"
        url = config.custom_base_url
        if not url:
            raise ValueError("custom_base_url is required for custom embedding providers")
        return OpenAIEmbeddingClient(api_key=key, model_name=config.model, base_url=url)
    else:
        raise ValueError(f"Unknown embedding provider: {config.provider}")

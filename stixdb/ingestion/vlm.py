"""
VLM-based image description for ingestion.

When a supported image file is ingested and a VLM is configured, this module
calls the vision model to produce a text description that is stored as a
searchable memory node.  All major providers are supported via the same
provider enum used by the LLM and embedding modules.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

from stixdb.config import VLMConfig, LLMProvider


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

_DESCRIPTION_PROMPT = """\
Describe this image thoroughly for semantic search and retrieval. Include:
- All visible text, labels, captions, and headings (exact wording)
- Charts, graphs, tables, and diagrams — describe their structure and data values
- Code snippets, formulas, or structured data shown
- People, objects, scenes, and their spatial arrangement
- Colors, layout, and visual hierarchy

Be comprehensive and specific. This description is the only representation \
of the image that will be stored and searched."""


def is_image_file(filepath: str | Path) -> bool:
    """Return True if the file has a supported image extension."""
    return Path(filepath).suffix.lower() in IMAGE_EXTENSIONS


def _mime_type(path: Path) -> str:
    return {
        ".jpg":  "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png":  "image/png",
        ".gif":  "image/gif",
        ".webp": "image/webp",
        ".bmp":  "image/bmp",
    }.get(path.suffix.lower(), "image/png")


class VLMDescriber:
    """
    Calls a vision-capable LLM to produce a text description of an image.

    Supported providers: OpenAI, Anthropic, Ollama, Custom (OpenAI-compatible).
    When ``provider == NONE`` the describer is disabled and ``enabled`` is False.
    """

    def __init__(self, config: VLMConfig) -> None:
        self.config = config

    @property
    def enabled(self) -> bool:
        return self.config.provider != LLMProvider.NONE and bool(self.config.model)

    async def describe(
        self,
        image_path: str | Path,
        filename: str = "",
        prompt: Optional[str] = None,
    ) -> str:
        """
        Return a text description of the image at *image_path*.

        Raises ``RuntimeError`` if the VLM is not enabled.
        Passes *prompt* to the model if given; otherwise uses the built-in
        comprehensive description prompt.
        """
        if not self.enabled:
            raise RuntimeError("VLM is not configured (provider=none or no model set).")

        path = Path(image_path)
        b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
        mime = _mime_type(path)
        user_prompt = prompt or _DESCRIPTION_PROMPT

        provider = self.config.provider
        if provider == LLMProvider.OPENAI:
            return await self._call_openai(b64, mime, user_prompt)
        elif provider == LLMProvider.ANTHROPIC:
            return await self._call_anthropic(b64, mime, user_prompt)
        elif provider == LLMProvider.OLLAMA:
            return await self._call_ollama(b64, user_prompt)
        elif provider == LLMProvider.CUSTOM:
            return await self._call_custom(b64, mime, user_prompt)
        else:
            raise ValueError(f"Unsupported VLM provider: {provider}")

    # ── Provider implementations ──────────────────────────────────────────── #

    async def _call_openai(self, b64: str, mime: str, prompt: str) -> str:
        from openai import AsyncOpenAI
        kwargs: dict = {}
        if self.config.openai_api_key:
            kwargs["api_key"] = self.config.openai_api_key
        client = AsyncOpenAI(**kwargs)
        resp = await client.chat.completions.create(
            model=self.config.model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }],
            max_tokens=1024,
        )
        return resp.choices[0].message.content or ""

    async def _call_anthropic(self, b64: str, mime: str, prompt: str) -> str:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=self.config.anthropic_api_key)
        resp = await client.messages.create(
            model=self.config.model,
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime,
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        return resp.content[0].text if resp.content else ""

    async def _call_ollama(self, b64: str, prompt: str) -> str:
        import httpx
        url = f"{self.config.ollama_base_url.rstrip('/')}/api/generate"
        payload = {
            "model": self.config.model,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            return r.json().get("response", "")

    async def _call_custom(self, b64: str, mime: str, prompt: str) -> str:
        """OpenAI-compatible vision endpoint (Nebius, OpenRouter, etc.)."""
        from openai import AsyncOpenAI
        kwargs: dict = {"base_url": self.config.custom_base_url}
        if self.config.custom_api_key:
            kwargs["api_key"] = self.config.custom_api_key
        client = AsyncOpenAI(**kwargs)
        resp = await client.chat.completions.create(
            model=self.config.model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }],
            max_tokens=1024,
        )
        return resp.choices[0].message.content or ""

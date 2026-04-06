"""
Reasoner — LLM-backed reasoning over the memory graph.

The Reasoner is responsible for producing CONTEXTUAL answers from
retrieved memory nodes. It supports three LLM providers:
  - OpenAI (default)
  - Anthropic Claude
  - Ollama (local)

It receives a question + a subgraph of relevant MemoryNodes and
constructs a reasoning prompt that forces the LLM to:
1. Explain which nodes are relevant and why
2. Synthesise a concise, grounded answer
3. Report what it doesn't know (honest uncertainty)
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Optional, Any, AsyncIterator

from tenacity import retry, stop_after_attempt, wait_exponential

from stixdb.graph.node import MemoryNode
from stixdb.config import LLMProvider, ReasonerConfig
from stixdb.observability.tracer import get_tracer


# ──────────────────────────────────────────────────────────────────────────── #
# Reasoning result                                                              #
# ──────────────────────────────────────────────────────────────────────────── #

@dataclass
class ReasoningResult:
    """Structured output from the Reasoner."""
    answer: Any
    reasoning_trace: str
    used_node_ids: list[str]
    confidence: float           # 0-1, self-reported by the LLM
    model_used: str
    latency_ms: float
    is_complete: bool = True
    suggested_query: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "reasoning_trace": self.reasoning_trace,
            "used_node_ids": self.used_node_ids,
            "confidence": self.confidence,
            "model_used": self.model_used,
            "latency_ms": self.latency_ms,
            "is_complete": self.is_complete,
            "suggested_query": self.suggested_query,
        }


@dataclass
class HopPlan:
    """Short user-facing thought plus the next retrieval query."""

    thought: str
    query: str


# ──────────────────────────────────────────────────────────────────────────── #
# System prompt and context builder                                             #
# ──────────────────────────────────────────────────────────────────────────── #

SYSTEM_PROMPT = """\
You are the internal reasoning agent of StixDB.
You answer from your own memory while staying grounded in the supporting source excerpts
available to you for this turn.

RULES:
1. Base your answer ONLY on the supporting source excerpts for this turn — do not hallucinate.
2. Speak as if you are using your own memory. Do NOT frame the answer as something "the collection says", "the database says", or "the memory says".
3. Do NOT mention internal implementation terms such as "memory nodes", "chunks", "retrieval", "database", "collection", or "context window".
4. If you need to refer to where information came from, say "the source", "the source text", or the source name if one is provided.
5. Prefer natural first-person language such as "I know", "I found", or "From the source text" when it fits.
6. Always cite which source IDs support your answer.
7. If the information is insufficient, say so explicitly.
8. Speak naturally to the user. Never say things like "the provided memory nodes say", "the collection tells me", or "the current memory does not contain".
9. Produce a structured JSON response with keys:
   - "reasoning": step-by-step explanation of how you derived the answer, using source-facing language
   - "answer": final concise answer (leave blank if more info is needed)
   - "used_node_ids": list of source IDs that were most relevant
   - "confidence": float 0-1 indicating your confidence in the answer
   - "status": "complete" OR "incomplete" (set to "incomplete" if you need more information to give a high confidence answer)
   - "next_query": (optional) if status is "incomplete", provide a search query to find the missing pieces
"""

STREAM_SYSTEM_PROMPT = """\
You are the internal reasoning agent of StixDB.
You answer from your own memory while staying grounded in the supporting source excerpts
available to you for this turn.

RULES:
1. Base your answer ONLY on the supporting source excerpts for this turn — do not hallucinate.
2. Stream the final answer immediately in plain natural language.
3. Speak as if you are using your own memory. Do NOT say "the collection says", "the database says", or similar.
4. If the information is insufficient, say so plainly instead of inventing details.
"""

HOP_PLAN_SYSTEM_PROMPT = """\
You are the live thinking narrator for StixDB.
Before each retrieval hop, produce one short first-person thought that sounds like a real ongoing investigation,
then propose the exact retrieval query to run next.

RULES:
1. The thought must be dynamically based on the user's question and the current awareness so far.
2. Keep the thought to one sentence, under 24 words, natural and conversational.
3. Do not mention internal terms like memory nodes, retrieval pipeline, database, or context window.
4. The query should be concrete and useful for semantic search.
5. Write like a contextual follow-up to what just happened, not like a generic task list.
6. Prefer thoughts such as "Ok, that gave me the SDK surface, now I need the exact ingest example." or "That angle was too broad, let me narrow it to the official Python guide."
7. If earlier hops were weak, say that naturally, like "I still haven't pinned down the query example, so I'll try the SDK docs directly."
8. Avoid robotic phrasing like "I need to find", "I need the exact", "I should find", or repeating the whole question verbatim unless necessary.
9. Vary the openings naturally: "Ok", "That helps", "I still don't have", "This is closer", "That angle was weak".
10. Return JSON only with:
   - "thought": short user-facing thought sentence
   - "query": the next retrieval query
"""

def get_system_prompt(custom_prompt: Optional[str] = None, output_schema: Optional[dict] = None, streaming: bool = False) -> str:
    base = custom_prompt or (STREAM_SYSTEM_PROMPT if streaming else SYSTEM_PROMPT)
    if output_schema and not streaming:
        base += f"\n\nCRITICAL: The 'answer' field in your JSON output MUST strictly be an object matching this JSON Schema:\n{json.dumps(output_schema, indent=2)}"
    return base

def build_context_prompt(question: str, nodes: list[MemoryNode]) -> str:
    node_context = ""
    for i, node in enumerate(nodes):
        source_name = node.source or node.metadata.get("source") or node.metadata.get("file_path") or "unknown source"
        node_context += (
            f"\n--- Source Excerpt {i + 1} ---\n"
            f"Source ID: {node.id}\n"
            f"Source Name: {source_name}\n"
            f"Type: {node.node_type.value}\n"
            f"Tier: {node.tier.value}\n"
            f"Importance: {node.importance:.2f}\n"
            f"Excerpt: {node.content}\n"
        )
        if node.metadata:
            node_context += f"Metadata: {json.dumps(node.metadata)}\n"

    return (
        f"QUERY: {question}\n\n"
        f"AVAILABLE SOURCE EXCERPTS ({len(nodes)} total):\n"
        f"{node_context}\n\n"
        "Respond strictly following the rules above."
    )


def build_hop_plan_prompt(
    *,
    question: str,
    current_query: str,
    prior_reasoning: Optional[str],
    nodes: list[MemoryNode],
    step_index: int,
    thinking_steps: int,
    hop_index: int,
    hops_per_step: int,
    last_query: Optional[str],
    last_new_nodes: int,
    last_confidence: Optional[float],
    low_progress_streak: int,
) -> str:
    awareness_lines: list[str] = []
    for node in nodes[-5:]:
        source_name = node.source or node.metadata.get("source") or node.metadata.get("file_path") or "unknown source"
        snippet = re.sub(r"\s+", " ", node.content or "").strip()
        if len(snippet) > 180:
            snippet = snippet[:177].rstrip() + "..."
        awareness_lines.append(f"- {source_name}: {snippet}")

    awareness = "\n".join(awareness_lines) if awareness_lines else "- No supporting excerpts yet."
    prior = re.sub(r"\s+", " ", prior_reasoning or "").strip()
    if len(prior) > 240:
        prior = prior[:237].rstrip() + "..."

    return (
        f"USER QUESTION: {question}\n"
        f"THINKING STEP: {step_index + 1}/{thinking_steps}\n"
        f"HOP: {hop_index + 1}/{hops_per_step}\n"
        f"CURRENT SEARCH ANGLE: {current_query}\n"
        f"LAST QUERY TRIED: {last_query or 'None yet.'}\n"
        f"LAST HOP NEW SOURCES: {last_new_nodes}\n"
        f"LAST HOP CONFIDENCE: {last_confidence if last_confidence is not None else 'unknown'}\n"
        f"LOW PROGRESS STREAK: {low_progress_streak}\n"
        f"CURRENT AWARENESS:\n{awareness}\n"
        f"LAST REASONING SUMMARY: {prior or 'None yet.'}\n\n"
        "Return only the JSON object."
    )


def _extract_chat_message_text(response: Any) -> str:
    if not getattr(response, "choices", None):
        return ""

    message = response.choices[0].message
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text_value = item.get("text") or item.get("content")
                if isinstance(text_value, str):
                    parts.append(text_value)
                continue
            text_value = getattr(item, "text", None) or getattr(item, "content", None)
            if isinstance(text_value, str):
                parts.append(text_value)
        return "".join(parts)

    refusal = getattr(message, "refusal", None)
    if isinstance(refusal, str):
        return refusal
    return ""


def _normalize_user_facing_text(text: str) -> str:
    replacements = [
        ("the collection tells me", "I found"),
        ("this collection tells me", "I found"),
        ("the collection says", "I found"),
        ("this collection says", "I found"),
        ("the collection describes", "I found"),
        ("this collection describes", "I found"),
        ("according to the collection", "from what I found"),
        ("in this collection", "in my memory"),
        ("provided memory nodes", "available source excerpts"),
        ("the provided memory nodes", "the available source excerpts"),
        ("current memory nodes", "available source excerpts"),
        ("memory nodes", "source excerpts"),
        ("memory node", "source excerpt"),
        ("current memory", "available sources"),
        ("in the current memory", "in the available sources"),
        ("from the current memory", "from the available sources"),
        ("knowledge base", "available sources"),
        ("chunks", "source excerpts"),
        ("chunk", "source excerpt"),
    ]
    normalized = text
    for old, new in replacements:
        normalized = normalized.replace(old, new)
        normalized = normalized.replace(old.capitalize(), new.capitalize())
    return normalized


def _normalize_hop_thought(text: str, fallback_question: str) -> str:
    thought = re.sub(r"\s+", " ", text or "").strip()
    if not thought:
        return f"Let me think through {fallback_question.strip()} a bit more."

    substitutions = [
        (r"^I need to find\b", "I still need to pin down"),
        (r"^I need the exact\b", "I still need the exact"),
        (r"^I need\b", "I still need"),
        (r"^I should\b", "Let me"),
        (r"^I will\b", "Let me"),
        (r"^I have to\b", "I still need to"),
    ]
    normalized = thought
    for pattern, replacement in substitutions:
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)

    normalized = _normalize_user_facing_text(normalized)
    if len(normalized) > 180:
        normalized = normalized[:177].rstrip() + "..."
    return normalized


# ──────────────────────────────────────────────────────────────────────────── #
# Reasoner                                                                      #
# ──────────────────────────────────────────────────────────────────────────── #

class Reasoner:
    """
    Multi-provider LLM reasoner.
    Stateless — a new ReasoningResult is produced for every call.
    """

    def __init__(self, config: ReasonerConfig) -> None:
        self.config = config
        self._tracer = get_tracer()

    async def plan_next_hop(
        self,
        *,
        question: str,
        current_query: str,
        nodes: list[MemoryNode],
        history: Optional[list[dict]] = None,
        prior_reasoning: Optional[str] = None,
        step_index: int = 0,
        thinking_steps: int = 1,
        hop_index: int = 0,
        hops_per_step: int = 1,
        last_query: Optional[str] = None,
        last_new_nodes: int = 0,
        last_confidence: Optional[float] = None,
        low_progress_streak: int = 0,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> HopPlan:
        """Generate a short live thought and the next retrieval query."""
        effective_temperature = self.config.temperature if temperature is None else temperature
        effective_max_tokens = min(250, self.config.max_tokens if max_tokens is None else max_tokens)
        prompt = build_hop_plan_prompt(
            question=question,
            current_query=current_query,
            prior_reasoning=prior_reasoning,
            nodes=nodes,
            step_index=step_index,
            thinking_steps=thinking_steps,
            hop_index=hop_index,
            hops_per_step=hops_per_step,
            last_query=last_query,
            last_new_nodes=last_new_nodes,
            last_confidence=last_confidence,
            low_progress_streak=low_progress_streak,
        )

        provider = self.config.provider
        if provider == LLMProvider.OPENAI:
            raw = await self._call_openai(
                question,
                nodes,
                HOP_PLAN_SYSTEM_PROMPT,
                history=history,
                temperature=effective_temperature,
                max_tokens=effective_max_tokens,
                user_prompt=prompt,
            )
        elif provider == LLMProvider.ANTHROPIC:
            raw = await self._call_anthropic(
                question,
                nodes,
                HOP_PLAN_SYSTEM_PROMPT,
                history=history,
                max_tokens=effective_max_tokens,
                user_prompt=prompt,
            )
        elif provider == LLMProvider.OLLAMA:
            raw = await self._call_ollama(
                question,
                nodes,
                HOP_PLAN_SYSTEM_PROMPT,
                history=history,
                max_tokens=effective_max_tokens,
                user_prompt=prompt,
            )
        elif provider == LLMProvider.CUSTOM:
            raw = await self._call_custom(
                question,
                nodes,
                HOP_PLAN_SYSTEM_PROMPT,
                history=history,
                temperature=effective_temperature,
                max_tokens=effective_max_tokens,
                user_prompt=prompt,
            )
        else:
            thought = f"Let me think through {question.strip()} a bit more."
            return HopPlan(thought=thought, query=current_query)

        return self._parse_hop_plan(raw, current_query=current_query, fallback_question=question)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def reason(
        self,
        collection: str,
        question: str,
        nodes: list[MemoryNode],
        history: Optional[list[dict]] = None,
        system_prompt: Optional[str] = None,
        output_schema: Optional[dict] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> ReasoningResult:
        """
        Core reasoning entry point.
        Takes a question + list of retrieved MemoryNodes and returns
        a structured ReasoningResult.
        """
        start = time.time()

        if not nodes:
            return ReasoningResult(
                answer="I have no relevant memories to answer this question.",
                reasoning_trace="No nodes were retrieved from the graph.",
                used_node_ids=[],
                confidence=0.0,
                model_used=self.config.model,
                latency_ms=0.0,
            )

        provider = self.config.provider
        sp = get_system_prompt(system_prompt, output_schema)
        effective_temperature = self.config.temperature if temperature is None else temperature
        effective_max_tokens = self.config.max_tokens if max_tokens is None else max_tokens

        if provider == LLMProvider.OPENAI:
            raw = await self._call_openai(
                question,
                nodes,
                sp,
                history=history,
                temperature=effective_temperature,
                max_tokens=effective_max_tokens,
            )
        elif provider == LLMProvider.ANTHROPIC:
            raw = await self._call_anthropic(
                question,
                nodes,
                sp,
                history=history,
                max_tokens=effective_max_tokens,
            )
        elif provider == LLMProvider.OLLAMA:
            raw = await self._call_ollama(
                question,
                nodes,
                sp,
                history=history,
                max_tokens=effective_max_tokens,
            )
        elif provider == LLMProvider.CUSTOM:
            raw = await self._call_custom(
                question,
                nodes,
                sp,
                history=history,
                temperature=effective_temperature,
                max_tokens=effective_max_tokens,
            )
        else:
            raw = self._heuristic_fallback(question, nodes)

        latency_ms = (time.time() - start) * 1000.0
        result = self._parse_response(raw, nodes, latency_ms)

        self._tracer.record_reasoning(
            collection=collection,
            question=question,
            reasoning_trace=result.reasoning_trace,
        )
        return result

    async def stream_reason(
        self,
        collection: str,
        question: str,
        nodes: list[MemoryNode],
        history: Optional[list[dict]] = None,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[dict]:
        """
        Streaming version of reasoning.
        Yields chunks with 'type' (thinking, answer, node_count, metadata).
        """
        if not nodes:
            yield {"type": "answer", "content": "I have no relevant memories to answer this question."}
            return

        yield {"type": "node_count", "count": len(nodes)}

        provider = self.config.provider
        sp = get_system_prompt(system_prompt, streaming=True)
        effective_temperature = self.config.temperature if temperature is None else temperature
        effective_max_tokens = self.config.max_tokens if max_tokens is None else max_tokens
        
        # We wrap history if provided
        messages = history or []
        # Prepend system prompt
        messages = [{"role": "system", "content": sp}] + messages
        # Append current context
        messages.append({"role": "user", "content": build_context_prompt(question, nodes)})

        if provider == LLMProvider.OPENAI or provider == LLMProvider.CUSTOM:
            api_key = self.config.openai_api_key if provider == LLMProvider.OPENAI else (self.config.custom_api_key or "dummy-key")
            base_url = None if provider == LLMProvider.OPENAI else self.config.custom_base_url
            
            import openai
            client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
            
            # For streaming, we don't use response_format=json_object because it often buffers
            # and is harder to parse token-by-token.
            # Instead we use a flat stream and guide the LLM to use tags.
            
            stream = await client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                temperature=effective_temperature,
                max_tokens=effective_max_tokens,
                stream=True,
                timeout=self.config.timeout_seconds,
            )

            raw_response = ""
            async for chunk in stream:
                content = chunk.choices[0].delta.content or ""
                if not content:
                    continue

                raw_response += content
                yield {"type": "answer", "content": _normalize_user_facing_text(content)}
            yield {"type": "metadata", "raw_response": raw_response}
        else:
            # Fallback to non-streaming for other providers for now
            res = await self.reason(
                collection,
                question,
                nodes,
                system_prompt=system_prompt,
                temperature=effective_temperature,
                max_tokens=effective_max_tokens,
            )
            if res.reasoning_trace:
                yield {"type": "thinking", "content": _normalize_user_facing_text(res.reasoning_trace)}
            yield {"type": "answer", "content": _normalize_user_facing_text(str(res.answer))}
            yield {"type": "metadata", "raw_response": json.dumps({
                "reasoning": res.reasoning_trace,
                "answer": res.answer,
                "used_node_ids": res.used_node_ids,
                "confidence": res.confidence,
                "status": "complete" if res.is_complete else "incomplete",
                "next_query": res.suggested_query,
            })}

    # ------------------------------------------------------------------ #
    # Provider implementations                                            #
    # ------------------------------------------------------------------ #

    async def _call_openai(
        self,
        question: str,
        nodes: list[MemoryNode],
        system_prompt: str,
        history: Optional[list[dict]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        user_prompt: Optional[str] = None,
    ) -> str:
        import openai
        import asyncio

        api_key = self.config.openai_api_key
        client = openai.AsyncOpenAI(api_key=api_key)

        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_prompt or build_context_prompt(question, nodes)})

        return await self._call_chat_completion_with_fallback(
            client=client,
            messages=messages,
            temperature=self.config.temperature if temperature is None else temperature,
            max_tokens=self.config.max_tokens if max_tokens is None else max_tokens,
        )

    async def _call_custom(
        self,
        question: str,
        nodes: list[MemoryNode],
        system_prompt: str,
        history: Optional[list[dict]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        user_prompt: Optional[str] = None,
    ) -> str:
        import openai

        api_key = self.config.custom_api_key or "dummy-key"
        base_url = self.config.custom_base_url
        client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)

        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_prompt or build_context_prompt(question, nodes)})

        return await self._call_chat_completion_with_fallback(
            client=client,
            messages=messages,
            temperature=self.config.temperature if temperature is None else temperature,
            max_tokens=self.config.max_tokens if max_tokens is None else max_tokens,
        )

    async def _call_chat_completion_with_fallback(
        self,
        client: Any,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> str:
        response = await client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            timeout=self.config.timeout_seconds,
        )
        content = _extract_chat_message_text(response).strip()
        if content:
            return content

        # Some reasoning/custom providers intermittently return an empty
        # content field when strict JSON mode is requested. Retry once
        # without response_format and with a stronger inline reminder.
        fallback_messages = list(messages)
        if fallback_messages:
            fallback_messages[0] = {
                "role": fallback_messages[0]["role"],
                "content": (
                    fallback_messages[0]["content"]
                    + "\n\nReturn a valid JSON object only. Do not return an empty response."
                ),
            }

        retry_response = await client.chat.completions.create(
            model=self.config.model,
            messages=fallback_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=self.config.timeout_seconds,
        )
        retry_content = _extract_chat_message_text(retry_response).strip()
        return retry_content

    async def _call_anthropic(
        self,
        question: str,
        nodes: list[MemoryNode],
        system_prompt: str,
        history: Optional[list[dict]] = None,
        max_tokens: Optional[int] = None,
        user_prompt: Optional[str] = None,
    ) -> str:
        import anthropic

        api_key = self.config.anthropic_api_key
        client = anthropic.AsyncAnthropic(api_key=api_key)

        response = await client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens if max_tokens is None else max_tokens,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt or build_context_prompt(question, nodes)}
            ],
        )
        return response.content[0].text

    async def _call_ollama(
        self,
        question: str,
        nodes: list[MemoryNode],
        system_prompt: str,
        history: Optional[list[dict]] = None,
        max_tokens: Optional[int] = None,
        user_prompt: Optional[str] = None,
    ) -> str:
        import httpx

        prompt = user_prompt or build_context_prompt(question, nodes)
        full_prompt = f"{system_prompt}\n\n{prompt}"

        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            response = await client.post(
                f"{self.config.ollama_base_url}/api/generate",
                json={
                    "model": self.config.model,
                    "prompt": full_prompt,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "num_predict": self.config.max_tokens if max_tokens is None else max_tokens,
                    },
                },
            )
            response.raise_for_status()
            return response.json()["response"]

    async def synthesize_nodes(self, nodes: list[MemoryNode]) -> str:
        """
        Synthesize a concise summary from a cluster of semantically related nodes.
        Returns plain text. Used by the Consolidator for LLM-backed merge summaries.
        Falls back to empty string silently so the consolidator can use concatenation.
        """
        if not nodes or self.config.provider == LLMProvider.NONE:
            return ""
        snippets = "\n\n".join(
            f"[{i + 1}] {n.content.strip()[:400]}" for i, n in enumerate(nodes[:8])
        )
        prompt = (
            f"These {len(nodes)} memory fragments are semantically related. "
            "Write a single concise synthesis (2-4 sentences) capturing the key facts. "
            "Include only information present in the sources. No preamble.\n\n"
            f"{snippets}"
        )
        return await self._call_plain_completion(prompt, max_tokens=300)

    async def _call_plain_completion(self, prompt: str, max_tokens: int = 300) -> str:
        """
        Make a raw LLM call and return plain text (no JSON format enforcement).
        Used for synthesis tasks that don't need structured output.
        """
        provider = self.config.provider
        system = "You are a memory consolidation assistant. Be factual and concise."
        try:
            if provider in (LLMProvider.OPENAI, LLMProvider.CUSTOM):
                import openai
                api_key = (
                    self.config.openai_api_key
                    if provider == LLMProvider.OPENAI
                    else (self.config.custom_api_key or "dummy-key")
                )
                base_url = None if provider == LLMProvider.OPENAI else self.config.custom_base_url
                client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
                response = await client.chat.completions.create(
                    model=self.config.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=max_tokens,
                    timeout=self.config.timeout_seconds,
                )
                return (response.choices[0].message.content or "").strip()
            elif provider == LLMProvider.ANTHROPIC:
                import anthropic
                client = anthropic.AsyncAnthropic(api_key=self.config.anthropic_api_key)
                message = await client.messages.create(
                    model=self.config.model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                )
                return message.content[0].text.strip() if message.content else ""
            elif provider == LLMProvider.OLLAMA:
                import httpx
                async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                    response = await client.post(
                        f"{self.config.ollama_base_url}/api/generate",
                        json={
                            "model": self.config.model,
                            "prompt": f"{system}\n\n{prompt}",
                            "stream": False,
                            "options": {"num_predict": max_tokens, "temperature": 0.1},
                        },
                    )
                    response.raise_for_status()
                    return response.json().get("response", "").strip()
        except Exception:
            return ""
        return ""

    def _heuristic_fallback(self, question: str, nodes: list[MemoryNode]) -> str:
        """
        When no LLM is configured, return the most relevant nodes as a
        structured summary. This is always available.
        """
        # Sort by importance
        sorted_nodes = sorted(nodes, key=lambda n: n.importance, reverse=True)[:5]
        summaries = [f"- [{n.node_type.value}] {n.content}" for n in sorted_nodes]
        answer = "\n".join(summaries)
        return json.dumps({
            "reasoning": "Heuristic fallback: ranked by importance score.",
            "answer": answer,
            "used_node_ids": [n.id for n in sorted_nodes],
            "confidence": 0.5,
        })

    # ------------------------------------------------------------------ #
    # Response parsing                                                     #
    # ------------------------------------------------------------------ #

    def _parse_response(
        self, raw: str | None, nodes: list[MemoryNode], latency_ms: float
    ) -> ReasoningResult:
        if not raw or raw.strip() == "":
            return ReasoningResult(
                answer="The reasoning model returned an empty response.",
                reasoning_trace="No content was generated by the LLM.",
                used_node_ids=[],
                confidence=0.0,
                model_used=self.config.model,
                latency_ms=latency_ms,
            )

        try:
            data = json.loads(raw)
            status = data.get("status", "complete")
            
            answer = data.get("answer")
            if answer is None or (isinstance(answer, str) and not answer.strip()):
                # Fallback to raw if logic dictates, but avoid literal "{}"
                if raw.strip() == "{}":
                    answer = "The model produced an empty structured result."
                else:
                    answer = raw

            return ReasoningResult(
                answer=_normalize_user_facing_text(str(answer)),
                reasoning_trace=_normalize_user_facing_text(data.get("reasoning", "")),
                used_node_ids=data.get("used_node_ids", []),
                confidence=float(data.get("confidence", 0.7)),
                model_used=self.config.model,
                latency_ms=latency_ms,
                is_complete=(status == "complete"),
                suggested_query=data.get("next_query"),
            )
        except (json.JSONDecodeError, ValueError):
            import re
            
            # Try parsing XML-like stream format
            r_match = re.search(r"<reasoning>(.*?)</reasoning>", raw, re.DOTALL)
            s_match = re.search(r"<status>(.*?)</status>", raw, re.DOTALL)
            nq_match = re.search(r"<next_query>(.*?)</next_query>", raw, re.DOTALL)
            a_match = re.search(r"<answer>(.*?)</answer>", raw, re.DOTALL)
            c_match = re.search(r"<confidence>(.*?)</confidence>", raw, re.DOTALL)
            
            if r_match or a_match:
                status_str = s_match.group(1).strip().lower() if s_match else "complete"
                nq_str = (nq_match.group(1).strip() if nq_match else None)
                if nq_str and nq_str.lower() == "none":
                    nq_str = None
                
                return ReasoningResult(
                    answer=_normalize_user_facing_text(a_match.group(1).strip() if a_match else raw),
                    reasoning_trace=_normalize_user_facing_text(r_match.group(1).strip() if r_match else ""),
                    used_node_ids=[n.id for n in nodes[:5]],
                    confidence=float(c_match.group(1).strip()) if c_match else 0.5,
                    model_used=self.config.model,
                    latency_ms=latency_ms,
                    is_complete=(status_str == "complete"),
                    suggested_query=nq_str
                )

            # Graceful degradation — return raw text
            return ReasoningResult(
                answer=_normalize_user_facing_text(raw),
                reasoning_trace="Could not parse structured reasoning.",
                used_node_ids=[n.id for n in nodes[:5]],
                confidence=0.4,
                model_used=self.config.model,
                latency_ms=latency_ms,
            )

    def _parse_hop_plan(
        self,
        raw: str | None,
        *,
        current_query: str,
        fallback_question: str,
    ) -> HopPlan:
        default_thought = f"Let me think through {fallback_question.strip()} a bit more."
        if not raw or not raw.strip():
            return HopPlan(thought=default_thought, query=current_query)

        thought = ""
        query = ""
        try:
            data = json.loads(raw)
            thought = re.sub(r"\s+", " ", str(data.get("thought", "")).strip())
            query = re.sub(r"\s+", " ", str(data.get("query", "")).strip())
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

        if not thought:
            thought = default_thought
        thought = _normalize_hop_thought(thought, fallback_question)

        if not query:
            query = current_query

        return HopPlan(thought=thought, query=query)

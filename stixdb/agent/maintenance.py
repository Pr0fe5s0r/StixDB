"""
Maintenance planner for self-evolving collections.

The planner inspects the current collection structure and proposes
high-value maintenance questions that help the agent maintain useful,
up-to-date summaries without flooding the graph with low-signal nodes.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from stixdb.graph.node import MemoryNode, NodeType, MemoryTier
from stixdb.graph.summary_index import extract_summary_related_node_ids

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "by", "for", "from",
    "has", "have", "how", "in", "into", "is", "it", "its", "of", "on", "or",
    "that", "the", "their", "this", "to", "was", "what", "when", "where",
    "which", "who", "why", "with", "without", "using", "used", "use",
    "can", "there", "them", "these", "those", "such", "than", "then", "will",
    "would", "could", "should", "about", "collection", "collections", "document",
    "documents", "paper", "section", "sections", "example", "examples", "upload",
    "uploaded", "file", "files", "chunk", "chunks", "summary", "summaries",
    "agent", "agents", "reasoning", "model", "models", "system", "demo",
    "tmp", "pdf", "txt", "md", "data", "information",
}

_GENERIC_SOURCE_NAMES = {
    "agent-consolidator",
    "agent-maintenance",
    "agent-reflection",
}


@dataclass
class MaintenanceQuestion:
    question: str
    summary_label: str
    kind: str
    reason: str
    priority: float
    focus_node_ids: list[str] = field(default_factory=list)
    focus_sources: list[str] = field(default_factory=list)
    focus_tags: list[str] = field(default_factory=list)
    focus_terms: list[str] = field(default_factory=list)

    @property
    def question_key(self) -> str:
        return hashlib.sha1(self.question.strip().lower().encode("utf-8")).hexdigest()


class MaintenancePlanner:
    """
    Heuristic planner that chooses maintenance questions from collection
    structure and coverage gaps.
    """

    def __init__(self, max_questions: int = 8) -> None:
        self.max_questions = max_questions

    def plan(
        self,
        collection: str,
        nodes: list[MemoryNode],
    ) -> list[MaintenanceQuestion]:
        active_nodes = [
            node for node in nodes
            if node.tier != MemoryTier.ARCHIVED
            and not self._is_internal_summary(node)
        ]
        if not active_nodes:
            return []

        maintenance_nodes = [
            node for node in nodes
            if node.node_type == NodeType.SUMMARY and node.source == "agent-maintenance"
        ]
        covered_node_ids = self._covered_node_ids(maintenance_nodes)

        candidates: list[MaintenanceQuestion] = []
        candidates.append(self._build_collection_overview(active_nodes, covered_node_ids))
        candidates.extend(self._build_verification_questions(active_nodes, covered_node_ids))
        candidates.extend(self._build_source_questions(active_nodes, covered_node_ids))
        candidates.extend(self._build_tag_questions(active_nodes, covered_node_ids))
        candidates.extend(self._build_keyword_gap_questions(active_nodes, covered_node_ids))
        candidates.extend(self._build_relationship_questions(collection, active_nodes))
        # Higher-quality question generation grounded in actual content
        candidates.extend(self._build_content_entity_questions(active_nodes, covered_node_ids))
        candidates.extend(self._build_user_query_derived_questions(nodes, covered_node_ids))

        deduped: dict[str, MaintenanceQuestion] = {}
        for candidate in candidates:
            existing = deduped.get(candidate.question_key)
            if existing is None or candidate.priority > existing.priority:
                deduped[candidate.question_key] = candidate

        ranked = list(deduped.values())
        ranked.sort(
            key=lambda item: (item.priority, len(item.focus_node_ids), item.question),
            reverse=True,
        )
        return ranked[: self.max_questions]

    def _build_collection_overview(
        self,
        nodes: list[MemoryNode],
        covered_node_ids: set[str],
    ) -> MaintenanceQuestion:
        uncovered = [node for node in nodes if node.id not in covered_node_ids]
        focus_nodes = self._top_nodes(uncovered or nodes, limit=10)
        sources = sorted({self._source_name(node) for node in focus_nodes if self._source_name(node)})
        terms = self._top_terms_from_nodes(focus_nodes, limit=4)
        reason = "Refresh the overall memory overview using the most important active nodes."
        if terms:
            reason += f" Dominant themes currently include {', '.join(terms)}."
        return MaintenanceQuestion(
            question="Summarize the current state of memory right now.",
            summary_label="Memory Overview",
            kind="collection_overview",
            reason=reason,
            priority=1.0 + 0.02 * len(uncovered),
            focus_node_ids=[node.id for node in focus_nodes],
            focus_sources=sources[:3],
            focus_terms=terms,
        )

    def _build_verification_questions(
        self,
        nodes: list[MemoryNode],
        covered_node_ids: set[str],
    ) -> list[MaintenanceQuestion]:
        workflow_terms = {
            "stixclient",
            "stixdb_sdk",
            "sdk",
            "ingest_folder",
            "openai",
            "chat",
            "completions",
            "stream",
            "verbose",
            "thinking",
            "model",
            "collection",
            "pdf",
            "parser",
            "docling",
            "legacy",
        }

        focus_nodes = self._top_nodes(
            [
                node for node in nodes
                if workflow_terms & self._term_set(node.content)
                or workflow_terms & {tag.lower() for tag in node.tags}
                or any(term in self._source_name(node).lower() for term in {"sdk", "openai", "compatibility"})
            ],
            limit=10,
        )
        if len(focus_nodes) < 2:
            return []

        uncovered = [node for node in focus_nodes if node.id not in covered_node_ids]
        effective_focus = uncovered or focus_nodes
        terms = self._top_terms_from_nodes(effective_focus, limit=6)

        return [
            MaintenanceQuestion(
                question=(
                    "Using the current SDK and API only, show the correct pattern for ingesting a folder "
                    "with StixDBClient and then asking via OpenAI-compatible /v1 chat. Verify each step "
                    "against the source text, keep only source-supported details, and correct anything "
                    "outdated, inconsistent, or suspicious."
                ),
                summary_label="Verified Workflow: SDK Ingest + OpenAI Chat",
                kind="workflow_verification",
                reason=(
                    "The memory contains SDK and OpenAI-compatibility material, so a verified workflow summary "
                    "helps prevent stale or mixed interface guidance from persisting."
                    + (f" Dominant terms include {', '.join(terms[:4])}." if terms else "")
                ),
                priority=1.15 + min(0.2, len(uncovered) * 0.02),
                focus_node_ids=[node.id for node in effective_focus],
                focus_sources=[self._source_name(node) for node in effective_focus if self._source_name(node)][:4],
                focus_terms=terms,
            )
        ]

    def _build_source_questions(
        self,
        nodes: list[MemoryNode],
        covered_node_ids: set[str],
    ) -> list[MaintenanceQuestion]:
        by_source: dict[str, list[MemoryNode]] = defaultdict(list)
        for node in nodes:
            source_name = self._source_name(node)
            if source_name:
                by_source[source_name].append(node)

        questions: list[MaintenanceQuestion] = []
        for source_name, source_nodes in by_source.items():
            uncovered = [node for node in source_nodes if node.id not in covered_node_ids]
            focus_nodes = self._top_nodes(uncovered or source_nodes, limit=8)
            coverage_ratio = 1.0 - (len(uncovered) / max(1, len(source_nodes)))
            terms = self._top_terms_from_nodes(focus_nodes, limit=3)
            source_label = self._source_label(source_name, focus_nodes)
            priority = 0.7 + min(0.25, len(uncovered) * 0.03) + (1.0 - coverage_ratio) * 0.2
            questions.append(
                MaintenanceQuestion(
                    question=(
                        f"Summarize the main ideas from {source_label}. Focus on {', '.join(terms[:2])}."
                        if terms else
                        f"Summarize the main ideas from {source_label}."
                    ),
                    summary_label=f"Source Summary: {source_label}",
                    kind="source_summary",
                    reason=(
                        f"Source '{source_label}' has {len(source_nodes)} active nodes and "
                        f"{len(uncovered)} are not covered by maintenance summaries."
                    ),
                    priority=priority,
                    focus_node_ids=[node.id for node in focus_nodes],
                    focus_sources=[source_label],
                    focus_terms=terms,
                )
            )

        questions.sort(key=lambda item: item.priority, reverse=True)
        return questions[:3]

    def _build_tag_questions(
        self,
        nodes: list[MemoryNode],
        covered_node_ids: set[str],
    ) -> list[MaintenanceQuestion]:
        by_tag: dict[str, list[MemoryNode]] = defaultdict(list)
        for node in nodes:
            for tag in node.tags:
                if not tag:
                    continue
                by_tag[tag.lower()].append(node)

        questions: list[MaintenanceQuestion] = []
        for tag, tag_nodes in by_tag.items():
            if len(tag_nodes) < 2:
                continue
            if self._is_generic_term(tag):
                continue
            uncovered = [node for node in tag_nodes if node.id not in covered_node_ids]
            focus_nodes = self._top_nodes(uncovered or tag_nodes, limit=6)
            priority = 0.55 + min(0.2, len(uncovered) * 0.04)
            questions.append(
                MaintenanceQuestion(
                    question=f"Summarize what is currently known about {tag}.",
                    summary_label=f"Topic Summary: {tag}",
                    kind="tag_summary",
                    reason=(
                        f"Tag '{tag}' appears across {len(tag_nodes)} active nodes and needs a stable summary."
                    ),
                    priority=priority,
                    focus_node_ids=[node.id for node in focus_nodes],
                    focus_tags=[tag],
                    focus_terms=self._top_terms_from_nodes(focus_nodes, limit=3),
                )
            )

        questions.sort(key=lambda item: item.priority, reverse=True)
        return questions[:2]

    def _build_keyword_gap_questions(
        self,
        nodes: list[MemoryNode],
        covered_node_ids: set[str],
    ) -> list[MaintenanceQuestion]:
        uncovered = [node for node in nodes if node.id not in covered_node_ids]
        if not uncovered:
            return []

        top_terms = self._top_terms_from_nodes(uncovered, limit=8)
        if not top_terms:
            return []

        questions: list[MaintenanceQuestion] = []
        for term in top_terms[:3]:
            focus_nodes = self._top_nodes(
                [node for node in uncovered if term in self._term_set(node.content)],
                limit=6,
            )
            if not focus_nodes:
                continue
            questions.append(
                MaintenanceQuestion(
                    question=f"Summarize the main claims or facts currently known about {term}.",
                    summary_label=f"Topic Summary: {term}",
                    kind="topic_gap",
                    reason=(
                        f"'{term}' is a repeated uncovered term in high-signal nodes and likely needs a maintained topic summary."
                    ),
                    priority=0.6 + min(0.2, len(focus_nodes) * 0.03),
                    focus_node_ids=[node.id for node in focus_nodes],
                    focus_terms=[term],
                )
            )
        return questions

    def _build_relationship_questions(
        self,
        collection: str,
        nodes: list[MemoryNode],
    ) -> list[MaintenanceQuestion]:
        top_terms = self._top_terms_from_nodes(nodes, limit=6)
        if len(top_terms) < 2:
            return []

        pair = top_terms[:2]
        related_nodes = self._top_nodes(
            [
                node for node in nodes
                if any(term in self._term_set(node.content) for term in pair)
            ],
            limit=8,
        )
        if len(related_nodes) < 3:
            return []

        return [
            MaintenanceQuestion(
                question=f"Summarize how {pair[0]} and {pair[1]} are related in the {collection} memory.",
                summary_label=f"Relationship Summary: {pair[0]} + {pair[1]}",
                kind="relationship",
                reason=(
                    f"'{pair[0]}' and '{pair[1]}' are dominant themes that co-occur across active nodes, "
                    "so maintaining their relationship summary improves higher-level structure."
                ),
                priority=0.58,
                focus_node_ids=[node.id for node in related_nodes],
                focus_terms=pair,
            )
        ]

    # ── Content-entity questions ──────────────────────────────────────────── #

    def _build_content_entity_questions(
        self,
        nodes: list[MemoryNode],
        covered_node_ids: set[str],
    ) -> list[MaintenanceQuestion]:
        """
        Mine ingested chunks for specific identifiers (class/function names,
        config keys, CLI flags) and generate targeted questions about them.
        These are far more useful than generic "summarize X" questions because
        they produce specific, actionable answers.
        """
        import re as _re

        # Patterns to extract meaningful identifiers from code/prose content
        _class_pat  = _re.compile(r"\bclass\s+([A-Z][A-Za-z0-9_]{2,})")
        _func_pat   = _re.compile(r"\bdef\s+([a-z_][a-z0-9_]{3,})\s*\(")
        _config_pat = _re.compile(r"\b(config|cfg|settings)\.[a-z_][a-z0-9_.]{3,}\b")
        _flag_pat   = _re.compile(r"--([a-z][a-z0-9-]{3,})\b")

        # Only look at uncovered ingested chunks (not internal agent nodes)
        candidate_nodes = [
            n for n in nodes
            if n.id not in covered_node_ids
            and n.source not in _GENERIC_SOURCE_NAMES
            and n.node_type != NodeType.SUMMARY
        ]

        # Collect entity → supporting nodes
        entity_nodes: dict[str, list[MemoryNode]] = {}
        for node in candidate_nodes:
            text = node.content or ""
            for pat, kind in (
                (_class_pat, "class"),
                (_func_pat, "function"),
                (_config_pat, "config"),
                (_flag_pat, "flag"),
            ):
                for match in pat.findall(text):
                    key = f"{kind}:{match.split('.')[-1]}"
                    if key not in entity_nodes:
                        entity_nodes[key] = []
                    entity_nodes[key].append(node)

        # Pick entities mentioned in multiple chunks — they're central concepts
        multi = {
            k: v for k, v in entity_nodes.items() if len(v) >= 2
        }
        if not multi:
            return []

        # Rank by occurrence count, pick top 3
        ranked = sorted(multi.items(), key=lambda kv: len(kv[1]), reverse=True)[:3]

        questions: list[MaintenanceQuestion] = []
        for key, source_nodes in ranked:
            kind, name = key.split(":", 1)
            focus = self._top_nodes(source_nodes, limit=6)

            if kind == "class":
                question = (
                    f"What does the {name} class do, what are its main methods, "
                    f"and how is it used in this codebase?"
                )
                label = f"Entity Summary: {name} (class)"
            elif kind == "function":
                question = (
                    f"What does the {name}() function do, what are its inputs and "
                    f"outputs, and where is it called from?"
                )
                label = f"Entity Summary: {name}() function"
            elif kind == "config":
                question = (
                    f"What is the {name} configuration setting, what values does it "
                    f"accept, and what behaviour does it control?"
                )
                label = f"Config Summary: {name}"
            else:  # flag
                question = (
                    f"What does the --{name} flag do, when should it be used, "
                    f"and what are its valid values?"
                )
                label = f"Flag Summary: --{name}"

            questions.append(
                MaintenanceQuestion(
                    question=question,
                    summary_label=label,
                    kind="entity_summary",
                    reason=(
                        f"'{name}' ({kind}) appears in {len(source_nodes)} source chunks "
                        f"and has not been summarised yet."
                    ),
                    # Higher than generic source-summary questions (0.7-0.95) so
                    # specific entity questions actually make it into the rotation.
                    priority=0.92 + min(0.18, len(source_nodes) * 0.02),
                    focus_node_ids=[n.id for n in focus],
                    focus_terms=[name],
                )
            )

        return questions

    def _build_user_query_derived_questions(
        self,
        nodes: list[MemoryNode],
        covered_node_ids: set[str],
    ) -> list[MaintenanceQuestion]:
        """
        Extract past user questions from stored answer/reasoning nodes and
        generate derivative follow-up questions from them.

        Past questions live in node.metadata["question"] on nodes with
        source="agent-reasoning" or source="agent-maintenance" (kind=workflow).
        """
        import re as _re

        past_questions: list[tuple[str, MemoryNode]] = []
        seen_questions: set[str] = set()

        for node in nodes:
            q = (node.metadata or {}).get("question", "")
            if not q or len(q) < 10:
                continue
            q_lower = q.strip().lower()
            # Skip maintenance/generated questions — only real user queries
            if any(phrase in q_lower for phrase in (
                "summarize", "summarise", "main ideas", "main claims",
                "what is currently known", "how are related",
            )):
                continue
            if q_lower in seen_questions:
                continue
            seen_questions.add(q_lower)
            past_questions.append((q.strip(), node))

        if not past_questions:
            return []

        questions: list[MaintenanceQuestion] = []

        for original_q, ref_node in past_questions[:4]:
            # Derive a "why/how" follow-up from the original question
            words = original_q.rstrip("?").strip()
            deriv = self._derive_followup(words)
            if not deriv:
                continue

            focus = self._top_nodes([ref_node], limit=6)
            questions.append(
                MaintenanceQuestion(
                    question=deriv,
                    summary_label=f"Follow-up: {words[:60]}",
                    kind="user_query_followup",
                    reason=(
                        f"Derived from past user question: \"{words[:80]}\". "
                        "Proactively filling in related context improves future retrieval."
                    ),
                    priority=0.85 + min(0.2, ref_node.importance * 0.2),
                    focus_node_ids=[n.id for n in focus],
                    focus_terms=self._top_terms_from_nodes(focus, limit=3),
                )
            )

        return questions

    def _derive_followup(self, question: str) -> str:
        """
        Produce a concrete follow-up question from a user question.
        Strategy: append "how" / "why" / "configuration" angle.
        """
        q = question.lower().strip()
        if q.startswith(("what ", "which ")):
            return f"How is {question[question.index(' ')+1:].rstrip('?')} configured and what are the available options?"
        if q.startswith("how "):
            return f"What are the exact steps and code needed to {question[4:].rstrip('?')}?"
        if q.startswith(("where ", "when ")):
            return f"Why does {question[question.index(' ')+1:].rstrip('?')} work this way, and are there edge cases to know about?"
        # Generic: "tell me more" style
        if len(question) > 20:
            return f"What are the implementation details and configuration options for: {question.rstrip('?')}?"
        return ""

    def _covered_node_ids(self, maintenance_nodes: Iterable[MemoryNode]) -> set[str]:
        covered: set[str] = set()
        for node in maintenance_nodes:
            metadata = node.metadata or {}
            covered.update(extract_summary_related_node_ids(metadata))
            for item in metadata.get("synthesized_from", []):
                covered.add(str(item))
        return covered

    def _top_nodes(self, nodes: list[MemoryNode], limit: int) -> list[MemoryNode]:
        ranked = sorted(
            nodes,
            key=lambda node: (
                node.importance,
                node.access_count,
                node.last_accessed,
            ),
            reverse=True,
        )
        return ranked[:limit]

    def _top_terms_from_nodes(self, nodes: list[MemoryNode], limit: int) -> list[str]:
        counter: Counter[str] = Counter()
        for node in nodes:
            counter.update(self._term_set(node.content))
        ranked = [
            term for term, count in counter.most_common(limit * 4)
            if not self._is_generic_term(term)
        ]
        return ranked[:limit]

    def _term_set(self, text: str) -> set[str]:
        words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", text.lower())
        return {
            word for word in words
            if word not in _STOPWORDS and not word.isdigit()
        }

    def _source_name(self, node: MemoryNode) -> str:
        metadata = node.metadata or {}
        source_name = str(
            node.source
            or metadata.get("filename")
            or metadata.get("source")
            or metadata.get("filepath")
            or ""
        ).strip()
        if self._ignore_source_name(source_name):
            return ""
        return source_name

    def _is_internal_summary(self, node: MemoryNode) -> bool:
        return node.node_type == NodeType.SUMMARY and node.source in {
            "agent-reflection",
            "agent-maintenance",
        }

    def _is_generic_term(self, term: str) -> bool:
        if not term:
            return True
        if term in _STOPWORDS:
            return True
        if term.startswith("tmp"):
            return True
        if len(term) <= 3:
            return True
        if term.isdigit():
            return True
        return False

    def _ignore_source_name(self, source_name: str) -> bool:
        lower = (source_name or "").strip().lower()
        if not lower:
            return True
        if lower in _GENERIC_SOURCE_NAMES:
            return True
        if re.match(r"tmp[a-z0-9_.-]+$", lower):
            return True
        return False

    def _source_label(self, source_name: str, nodes: list[MemoryNode]) -> str:
        if source_name and not self._ignore_source_name(source_name):
            return source_name

        for node in nodes:
            inferred = self._infer_title_from_content(node.content)
            if inferred:
                return inferred

        dominant_terms = self._top_terms_from_nodes(nodes, limit=2)
        if dominant_terms:
            return "topic " + " and ".join(dominant_terms)
        return "this source"

    def _infer_title_from_content(self, content: str) -> str:
        for line in content.splitlines():
            cleaned = re.sub(r"\s+", " ", line).strip(" -:\t")
            if not cleaned:
                continue
            if len(cleaned) < 8 or len(cleaned) > 120:
                continue
            if self._is_generic_term(cleaned.lower()):
                continue
            return cleaned
        return ""

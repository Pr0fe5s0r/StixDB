"""
Observability — Thinking Traces + Prometheus Metrics.

The tracer records every agent decision so you can audit *why*
the DB reorganised its memory. Thinking traces are stored in a
rotating in-memory buffer and exposed via the /trace API endpoint.

Prometheus metrics are exposed on a configurable port for scraping
by Grafana, Datadog, etc.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

# Optional Prometheus import
try:
    from prometheus_client import Counter, Histogram, Gauge, start_http_server
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False


# ──────────────────────────────────────────────────────────────────────────── #
# Thinking Trace data structures                                               #
# ──────────────────────────────────────────────────────────────────────────── #

@dataclass
class ThinkingTrace:
    """A single recorded agent thought."""
    timestamp: float = field(default_factory=time.time)
    collection: str = ""
    event_type: str = ""     # "query", "user_query", "maintenance_query", "maintenance_summary_refresh", ...
    summary: str = ""
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "collection": self.collection,
            "event_type": self.event_type,
            "summary": self.summary,
            "details": self.details,
        }


# ──────────────────────────────────────────────────────────────────────────── #
# Tracer singleton                                                             #
# ──────────────────────────────────────────────────────────────────────────── #

class STIXTracer:
    """
    Records agent thinking traces and exposes Prometheus metrics.
    
    Traces are kept in a fixed-size deque (ring buffer) to avoid
    unbounded memory growth. Adjust max_traces for your use case.
    """

    def __init__(self, max_traces: int = 10_000, enable_metrics: bool = True, metrics_port: int = 9090) -> None:
        self._traces: deque[ThinkingTrace] = deque(maxlen=max_traces)
        self._metrics_started = False
        self._enable_metrics = enable_metrics and _PROMETHEUS_AVAILABLE
        self._metrics_port = metrics_port

        if self._enable_metrics:
            self._init_metrics()

    def _init_metrics(self) -> None:
        self.queries_total = Counter(
            "stix_queries_total", "Total agentic queries processed", ["collection"]
        )
        self.nodes_stored = Counter(
            "stix_nodes_stored_total", "Total memory nodes stored", ["collection"]
        )
        self.nodes_pruned = Counter(
            "stix_nodes_pruned_total", "Total nodes pruned by consolidator", ["collection"]
        )
        self.nodes_merged = Counter(
            "stix_nodes_merged_total", "Total node merge operations", ["collection"]
        )
        self.query_latency = Histogram(
            "stix_query_latency_seconds", "Query end-to-end latency", ["collection"]
        )
        self.active_nodes = Gauge(
            "stix_active_nodes", "Current node count per collection", ["collection"]
        )
        self.agent_cycles = Counter(
            "stix_agent_cycles_total", "Total memory agent cycles", ["collection"]
        )

    def start_metrics_server(self) -> None:
        """Start the Prometheus exposition server (call once at startup)."""
        if self._enable_metrics and not self._metrics_started:
            try:
                start_http_server(self._metrics_port)
                self._metrics_started = True
            except Exception:
                pass  # port may already be in use

    # ------------------------------------------------------------------ #
    # Recording events                                                     #
    # ------------------------------------------------------------------ #

    def record_query(
        self,
        collection: str,
        question: str,
        nodes_retrieved: int,
        latency_ms: float,
        reasoning_summary: str,
        query_origin: str = "user",
    ) -> None:
        event_type = "maintenance_query" if query_origin == "maintenance" else "user_query"
        self._traces.append(ThinkingTrace(
            collection=collection,
            event_type=event_type,
            summary=f"Query answered in {latency_ms:.0f}ms using {nodes_retrieved} nodes",
            details={
                "question": question[:200],
                "nodes_retrieved": nodes_retrieved,
                "latency_ms": latency_ms,
                "reasoning": reasoning_summary[:500],
                "query_origin": query_origin,
            },
        ))
        self._traces.append(ThinkingTrace(
            collection=collection,
            event_type="query",
            summary=f"{query_origin.title()} query answered in {latency_ms:.0f}ms using {nodes_retrieved} nodes",
            details={
                "question": question[:200],
                "nodes_retrieved": nodes_retrieved,
                "latency_ms": latency_ms,
                "query_origin": query_origin,
            },
        ))
        if self._enable_metrics:
            self.queries_total.labels(collection=collection).inc()
            self.query_latency.labels(collection=collection).observe(latency_ms / 1000.0)

    def record_maintenance_summary_refresh(
        self,
        collection: str,
        summary_label: str,
        supporting_node_count: int,
        refreshed: bool,
        planner_reason: str,
    ) -> None:
        action = "refreshed" if refreshed else "created"
        self._traces.append(ThinkingTrace(
            collection=collection,
            event_type="maintenance_summary_refresh",
            summary=f"Maintenance summary {action}: {summary_label}",
            details={
                "summary_label": summary_label,
                "supporting_node_count": supporting_node_count,
                "refreshed": refreshed,
                "planner_reason": planner_reason[:500],
            },
        ))

    def record_node_stored(self, collection: str, node_id: str, content_preview: str) -> None:
        self._traces.append(ThinkingTrace(
            collection=collection,
            event_type="store",
            summary=f"Node {node_id[:8]} stored: {content_preview[:80]}",
            details={"node_id": node_id},
        ))
        if self._enable_metrics:
            self.nodes_stored.labels(collection=collection).inc()

    def record_consolidation(
        self,
        collection: str,
        merged: int,
        pruned: int,
        thoughts: list[str],
    ) -> None:
        self._traces.append(ThinkingTrace(
            collection=collection,
            event_type="consolidation",
            summary=f"Consolidated: {merged} merged, {pruned} pruned",
            details={"merged": merged, "pruned": pruned, "thoughts": thoughts[:20]},
        ))
        if self._enable_metrics:
            self.nodes_merged.labels(collection=collection).inc(merged)
            self.nodes_pruned.labels(collection=collection).inc(pruned)

    def record_tier_change(self, collection: str, node_id: str, old_tier: str, new_tier: str, reason: str) -> None:
        self._traces.append(ThinkingTrace(
            collection=collection,
            event_type="promotion",
            summary=f"Node {node_id[:8]} moved {old_tier} → {new_tier}: {reason}",
            details={"node_id": node_id, "old_tier": old_tier, "new_tier": new_tier, "reason": reason},
        ))

    def record_agent_cycle(self, collection: str, cycle_num: int, duration_ms: float) -> None:
        self._traces.append(ThinkingTrace(
            collection=collection,
            event_type="agent_cycle",
            summary=f"Agent cycle #{cycle_num} completed in {duration_ms:.0f}ms",
            details={"cycle_num": cycle_num, "duration_ms": duration_ms},
        ))
        if self._enable_metrics:
            self.agent_cycles.labels(collection=collection).inc()

    def record_reasoning(self, collection: str, question: str, reasoning_trace: str) -> None:
        self._traces.append(ThinkingTrace(
            collection=collection,
            event_type="reasoning",
            summary=f"LLM reasoning for: {question[:80]}",
            details={"question": question[:300], "reasoning": reasoning_trace[:1000]},
        ))

    # ------------------------------------------------------------------ #
    # Retrieval                                                            #
    # ------------------------------------------------------------------ #

    def get_traces(
        self,
        collection: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        traces = list(self._traces)
        if collection:
            traces = [t for t in traces if t.collection == collection]
        if event_type:
            traces = [t for t in traces if t.event_type == event_type]
        return [t.to_dict() for t in reversed(traces)][:limit]

    def get_stats(self) -> dict:
        return {
            "total_traces": len(self._traces),
            "buffer_capacity": self._traces.maxlen,
            "metrics_enabled": self._enable_metrics,
            "metrics_running": self._metrics_started,
        }


# ──────────────────────────────────────────────────────────────────────────── #
# Module-level singleton                                                       #
# ──────────────────────────────────────────────────────────────────────────── #

_tracer_instance: Optional[STIXTracer] = None


def init_tracer(
    max_traces: int = 10_000,
    enable_metrics: bool = True,
    metrics_port: int = 9090,
) -> STIXTracer:
    global _tracer_instance
    _tracer_instance = STIXTracer(
        max_traces=max_traces,
        enable_metrics=enable_metrics,
        metrics_port=metrics_port,
    )
    return _tracer_instance


def get_tracer() -> STIXTracer:
    global _tracer_instance
    if _tracer_instance is None:
        _tracer_instance = STIXTracer(enable_metrics=False)
    return _tracer_instance

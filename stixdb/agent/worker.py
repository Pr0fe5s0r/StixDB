"""
MemoryAgentWorker — decoupled background worker for the Memory Agent.

The Worker runs the perceive-plan-act loop in an isolated async task so
it never blocks query-serving code. It uses APScheduler for reliable
interval-based scheduling with proper error isolation.

Each collection gets exactly ONE worker instance. The worker is
lifecycle-managed by the StixDBEngine (start at init, stop at shutdown).
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Optional

from stixdb.graph.memory_graph import MemoryGraph
from stixdb.agent.planner import AccessPlanner
from stixdb.agent.consolidator import Consolidator
from stixdb.config import AgentConfig
from stixdb.observability.tracer import get_tracer

import structlog

logger = structlog.get_logger(__name__)


class WorkerState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class WorkerStatus:
    state: WorkerState = WorkerState.IDLE
    cycle_count: int = 0
    last_cycle_at: Optional[float] = None
    last_cycle_duration_ms: Optional[float] = None
    last_error: Optional[str] = None
    collection: str = ""


class MemoryAgentWorker:
    """
    Autonomous background worker that runs the Memory Agent cycle.
    
    Cycle steps:
    1. PERCEIVE  — collect access pattern data
    2. PLAN      — compute tier promotion / demotion decisions
    3. ACT       — apply decisions, run consolidation
    
    The worker is resilient: any exception in a cycle is caught and logged,
    but won't terminate the worker loop.
    """

    def __init__(
        self,
        graph: MemoryGraph,
        planner: AccessPlanner,
        consolidator: Consolidator,
        config: AgentConfig,
    ) -> None:
        self.graph = graph
        self.planner = planner
        self.consolidator = consolidator
        self.config = config
        self._tracer = get_tracer()

        self._status = WorkerStatus(collection=graph.collection)
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._maintenance_callback: Optional[Callable[[], Awaitable[dict]]] = None

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        """Start the background worker loop."""
        if self._task is not None and not self._task.done():
            return  # Already running
        self._stop_event.clear()
        self._status.state = WorkerState.RUNNING
        self._task = asyncio.create_task(self._run_loop(), name=f"stix-agent-{self.graph.collection}")
        logger.info("Memory agent worker started", collection=self.graph.collection)

    async def stop(self) -> None:
        """Gracefully stop the worker."""
        self._stop_event.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=10.0)
            except asyncio.TimeoutError:
                self._task.cancel()
        self._status.state = WorkerState.STOPPED
        logger.info("Memory agent worker stopped", collection=self.graph.collection)

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def get_status(self) -> dict:
        return {
            "collection": self._status.collection,
            "state": self._status.state.value,
            "cycle_count": self._status.cycle_count,
            "last_cycle_at": self._status.last_cycle_at,
            "last_cycle_duration_ms": self._status.last_cycle_duration_ms,
            "last_error": self._status.last_error,
            "planner_stats": self.planner.get_stats(),
        }

    def set_maintenance_callback(
        self,
        callback: Optional[Callable[[], Awaitable[dict]]],
    ) -> None:
        self._maintenance_callback = callback

    # ------------------------------------------------------------------ #
    # The Agent Loop                                                        #
    # ------------------------------------------------------------------ #

    async def _run_loop(self) -> None:
        """Main async loop — runs until stop() is called."""
        while not self._stop_event.is_set():
            try:
                await self._run_cycle()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._status.state = WorkerState.ERROR
                self._status.last_error = str(exc)
                logger.exception("Memory agent cycle failed", error=str(exc))
                # Don't crash the worker — wait and retry
                self._status.state = WorkerState.RUNNING

            # Wait for the next cycle interval (interruptible by stop event)
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.config.cycle_interval_seconds,
                )
            except asyncio.TimeoutError:
                pass  # Normal — interval elapsed, run next cycle

    async def _run_cycle(self) -> None:
        """One complete perceive → plan → act cycle."""
        cycle_start = time.time()
        collection = self.graph.collection

        logger.debug("Agent cycle starting", collection=collection, cycle=self._status.cycle_count)

        # ── PERCEIVE ────────────────────────────────────────────────────
        # (Access pattern data is collected reactively via record_access()
        #  calls from the Context Broker — nothing to do here explicitly.)

        # ── PLAN ────────────────────────────────────────────────────────
        plan = await self.planner.plan()
        promotes = len(plan.get("promote_to_working", []))
        demotes = len(plan.get("demote_from_working", []))
        archives = len(plan.get("candidates_for_archive", []))

        # ── ACT ─────────────────────────────────────────────────────────
        # Apply tier changes
        await self.planner.apply_promotions(plan)

        # Run consolidation (merge + prune + cluster rebuild)
        consolidation_result = await self.consolidator.run_cycle()
        maintenance_result = None
        if self._maintenance_callback is not None:
            maintenance_result = await self._maintenance_callback()

        # Update status
        duration_ms = (time.time() - cycle_start) * 1000
        self._status.cycle_count += 1
        self._status.last_cycle_at = time.time()
        self._status.last_cycle_duration_ms = duration_ms
        self._status.last_error = None

        # Emit trace
        self._tracer.record_agent_cycle(
            collection=collection,
            cycle_num=self._status.cycle_count,
            duration_ms=duration_ms,
        )

        logger.info(
            "Agent cycle complete",
            collection=collection,
            cycle=self._status.cycle_count,
            promotes=promotes,
            demotes=demotes,
            merged=len(consolidation_result.merged_pairs),
            pruned=len(consolidation_result.pruned_node_ids),
            maintenance_updates=(maintenance_result or {}).get("updated", 0),
            duration_ms=f"{duration_ms:.1f}",
        )

    def record_access(self, node_id: str) -> None:
        """Thread-safe access recording — delegates to the planner."""
        self.planner.record_access(node_id)

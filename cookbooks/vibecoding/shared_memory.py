"""
Vibecoding — Shared Agent Memory
=================================
Persistent, shared memory for vibecoding sessions. Any agent (Claude Code,
custom LLM agent, or script) can read and write to the same memory store
so context is never lost between sessions or across agents.

Usage (CLI — call from any agent or terminal):
    python cookbooks/vibecoding/shared_memory.py store "We use tRPC, not REST"
    python cookbooks/vibecoding/shared_memory.py ask "What API pattern do we use?"
    python cookbooks/vibecoding/shared_memory.py context
    python cookbooks/vibecoding/shared_memory.py ingest ./src
    python cookbooks/vibecoding/shared_memory.py status
    python cookbooks/vibecoding/shared_memory.py bug "useEffect with stale closure on socket — include socket in deps"
    python cookbooks/vibecoding/shared_memory.py decision "Switched from REST to tRPC for end-to-end type safety"

Usage (Python import — embed in your own agent):
    from cookbooks.vibecoding.shared_memory import VibecodeMemory
    mem = VibecodeMemory(project="my_project")
    async with mem:
        await mem.store_decision("Using Zustand for state management")
        ctx = await mem.restore_context()
        print(ctx)

Setup:
    pip install "stixdb-engine[local-dev]"

    # Optional — enables ask() and full reasoning
    export ANTHROPIC_API_KEY=sk-ant-...
    # or
    export OPENAI_API_KEY=sk-...

    python cookbooks/vibecoding/shared_memory.py
"""

import asyncio
import argparse
import os
import sys
import textwrap
from datetime import datetime
from pathlib import Path

from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import StorageConfig, StorageMode, ReasonerConfig, LLMProvider

# ── Default config ────────────────────────────────────────────────────────────
# Memory is stored here — shared by all agents on this machine.
# Change STIXDB_VIBE_PATH to move it or point multiple machines at a shared volume.
DEFAULT_MEMORY_PATH = os.getenv("STIXDB_VIBE_PATH", "./vibecode_memory")
DEFAULT_PROJECT     = os.getenv("STIXDB_VIBE_PROJECT", "vibecode")


# ── Auto-detect LLM provider ─────────────────────────────────────────────────
def _detect_reasoner() -> ReasonerConfig:
    """Pick the best available LLM from environment, fall back to heuristic mode."""
    if os.getenv("ANTHROPIC_API_KEY"):
        return ReasonerConfig(
            provider=LLMProvider.ANTHROPIC,
            model="claude-sonnet-4-6",
            temperature=0.1,
            max_tokens=1024,
            max_context_nodes=20,
        )
    if os.getenv("OPENAI_API_KEY"):
        return ReasonerConfig(
            provider=LLMProvider.OPENAI,
            model="gpt-4o",
            temperature=0.1,
            max_tokens=1024,
            max_context_nodes=20,
        )
    # No API key — still works, just no synthesized answers
    return ReasonerConfig(provider=LLMProvider.NONE)


def _build_config(memory_path: str) -> StixDBConfig:
    return StixDBConfig(
        storage=StorageConfig(
            mode=StorageMode.KUZU,
            kuzu_path=memory_path,
        ),
        reasoner=_detect_reasoner(),
    )


# ── VibecodeMemory class ──────────────────────────────────────────────────────

class VibecodeMemory:
    """
    Shared memory layer for vibecoding agents.

    All agents (Claude Code, custom scripts, CI pipelines) that point at the
    same `memory_path` share the same knowledge graph. StixDB's background
    agent continuously merges duplicates and decays stale facts, so you never
    need to clean it manually.

    Example
    -------
    mem = VibecodeMemory(project="my_app")
    async with mem:
        await mem.store_decision("Switched to Zustand for state management")
        ctx = await mem.restore_context()
    """

    def __init__(self, project: str = DEFAULT_PROJECT, memory_path: str = DEFAULT_MEMORY_PATH):
        self.project = project
        self.memory_path = memory_path
        self._config = _build_config(memory_path)
        self._engine: StixDBEngine | None = None

    async def __aenter__(self):
        self._engine = StixDBEngine(config=self._config)
        await self._engine.__aenter__()
        return self

    async def __aexit__(self, *args):
        if self._engine:
            await self._engine.__aexit__(*args)

    # ── Write helpers ─────────────────────────────────────────────────────────

    async def store_decision(self, text: str) -> None:
        """Store an architectural or design decision."""
        await self._engine.store(
            self.project,
            f"[DECISION] {text}",
            node_type="concept",
            tags=["decision", "architecture"],
            importance=0.9,
        )

    async def store_bug(self, text: str) -> None:
        """Store a bug fix so the agent never repeats the same mistake."""
        await self._engine.store(
            self.project,
            f"[BUG FIXED] {text}",
            node_type="fact",
            tags=["bug", "fix"],
            importance=0.85,
        )

    async def store_pattern(self, text: str) -> None:
        """Store a code pattern or convention in use."""
        await self._engine.store(
            self.project,
            f"[PATTERN] {text}",
            node_type="concept",
            tags=["pattern", "convention"],
            importance=0.8,
        )

    async def store_progress(self, text: str) -> None:
        """Store current session progress — what was done, what's next."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        await self._engine.store(
            self.project,
            f"[PROGRESS {ts}] {text}",
            node_type="event",
            tags=["progress", "session"],
            importance=0.75,
        )

    async def store(self, text: str, tags: list[str] | None = None) -> None:
        """General-purpose store — use when no specific type fits."""
        await self._engine.store(
            self.project,
            text,
            node_type="fact",
            tags=tags or ["general"],
            importance=0.7,
        )

    async def ingest_codebase(self, folder: str, recursive: bool = True) -> int:
        """
        Index an entire source folder into memory.
        Safe to re-run — StixDB deduplicates at the chunk level.
        Returns number of files ingested.
        """
        p = Path(folder)
        if not p.exists():
            raise FileNotFoundError(f"Folder not found: {folder}")
        stats_before = await self._engine.get_collection_stats(self.project)
        nodes_before = stats_before.get("total_nodes", 0)

        await self._engine.ingest_folder(
            self.project,
            folderpath=str(p),
            recursive=recursive,
        )

        stats_after = await self._engine.get_collection_stats(self.project)
        nodes_after = stats_after.get("total_nodes", 0)
        return nodes_after - nodes_before

    # ── Read helpers ──────────────────────────────────────────────────────────

    async def restore_context(self, top_k: int = 10) -> str:
        """
        Return a plain-text summary of the most important project context.
        Call this at the start of every session to ground the agent.
        """
        reasoner = self._config.reasoner

        if reasoner.provider != LLMProvider.NONE:
            # Full LLM synthesis
            response = await self._engine.ask(
                self.project,
                question=(
                    "Summarize the current state of this project for a developer "
                    "starting a new coding session. Include: key architectural decisions, "
                    "active patterns and conventions, recent progress, and any known bugs "
                    "or gotchas to avoid."
                ),
                top_k=top_k,
            )
            lines = [
                f"=== Project Context: {self.project} ===",
                "",
                response.answer,
                "",
                f"[confidence: {response.confidence:.0%} | sources: {len(response.sources)}]",
            ]
            return "\n".join(lines)

        else:
            # No LLM — return raw top-K nodes ranked by importance
            results = await self._engine.retrieve(
                self.project,
                query="project decisions patterns progress bugs",
                top_k=top_k,
            )
            lines = [f"=== Project Context: {self.project} (heuristic mode) ===", ""]
            for r in results:
                lines.append(f"• {r['content']}")
            lines += ["", "(Set ANTHROPIC_API_KEY or OPENAI_API_KEY for synthesized context)"]
            return "\n".join(lines)

    async def ask(self, question: str, top_k: int = 8) -> str:
        """Ask any question against the project memory."""
        reasoner = self._config.reasoner

        if reasoner.provider != LLMProvider.NONE:
            response = await self._engine.ask(self.project, question=question, top_k=top_k)
            lines = [
                f"Q: {question}",
                f"A: {response.answer}",
                f"   [confidence: {response.confidence:.0%}]",
            ]
            if response.sources:
                lines.append("   Sources:")
                for s in response.sources[:3]:
                    lines.append(f"     • {s.content[:120]}")
            return "\n".join(lines)

        else:
            results = await self._engine.retrieve(self.project, query=question, top_k=top_k)
            lines = [f"Q: {question}", "Closest memories:"]
            for r in results:
                lines.append(f"  [{r['score']:.2f}] {r['content']}")
            return "\n".join(lines)

    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Raw semantic search — returns list of result dicts."""
        return await self._engine.retrieve(self.project, query=query, top_k=top_k)

    async def status(self) -> str:
        """Return a brief status string about the memory store."""
        stats  = await self._engine.get_collection_stats(self.project)
        agent  = await self._engine.get_agent_status(self.project)
        reasoner_name = self._config.reasoner.provider.value

        lines = [
            f"=== StixDB Memory Status: {self.project} ===",
            f"  Path       : {self.memory_path}",
            f"  LLM        : {reasoner_name}",
            f"  Nodes      : {stats.get('total_nodes', 0)}",
            f"  Edges      : {stats.get('total_edges', 0)}",
            f"  Tiers      : {stats.get('nodes_by_tier', {})}",
            f"  Cycles     : {agent.get('cycles_completed', 0)}",
            f"  Last cycle : {agent.get('last_cycle_duration_ms', 0):.0f}ms",
            f"  Agent      : {agent.get('status', 'unknown')}",
        ]
        return "\n".join(lines)


# ── CLI entry point ───────────────────────────────────────────────────────────

async def cli_main(args: argparse.Namespace) -> None:
    async with VibecodeMemory(project=args.project, memory_path=args.memory_path) as mem:

        if args.command == "store":
            await mem.store(" ".join(args.text))
            print(f"Stored: {' '.join(args.text)}")

        elif args.command == "decision":
            await mem.store_decision(" ".join(args.text))
            print(f"Decision stored.")

        elif args.command == "bug":
            await mem.store_bug(" ".join(args.text))
            print(f"Bug fix stored.")

        elif args.command == "pattern":
            await mem.store_pattern(" ".join(args.text))
            print(f"Pattern stored.")

        elif args.command == "progress":
            await mem.store_progress(" ".join(args.text))
            print(f"Progress stored.")

        elif args.command == "ask":
            result = await mem.ask(" ".join(args.text))
            print(result)

        elif args.command == "context":
            result = await mem.restore_context()
            print(result)

        elif args.command == "ingest":
            folder = args.text[0] if args.text else "."
            print(f"Ingesting {folder} ...")
            added = await mem.ingest_codebase(folder)
            print(f"Done. {added} new nodes added.")

        elif args.command == "status":
            result = await mem.status()
            print(result)

        else:
            print(f"Unknown command: {args.command}")
            sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shared_memory",
        description=textwrap.dedent("""\
            StixDB Vibecoding — Shared Agent Memory CLI

            Persistent memory for vibecoding sessions. Any agent or script that
            points at the same --memory-path shares the same knowledge graph.
        """),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              # Store an architectural decision
              python shared_memory.py decision "We use tRPC, not REST"

              # Store a bug fix
              python shared_memory.py bug "useEffect stale closure on socket — add socket to deps array"

              # Restore context at the start of a session
              python shared_memory.py context

              # Ask a question
              python shared_memory.py ask "How does authentication work?"

              # Index the entire source tree
              python shared_memory.py ingest ./src

              # Check memory health
              python shared_memory.py status

            Environment variables:
              ANTHROPIC_API_KEY   — enables Claude reasoning
              OPENAI_API_KEY      — enables GPT-4o reasoning
              STIXDB_VIBE_PATH    — override memory storage path (default: ./vibecode_memory)
              STIXDB_VIBE_PROJECT — override project/collection name (default: vibecode)
        """),
    )
    parser.add_argument(
        "command",
        choices=["store", "decision", "bug", "pattern", "progress", "ask", "context", "ingest", "status"],
        help="Action to perform",
    )
    parser.add_argument(
        "text",
        nargs="*",
        help="Text content (not required for 'context' and 'status')",
    )
    parser.add_argument(
        "--project",
        default=DEFAULT_PROJECT,
        help=f"Collection name (default: {DEFAULT_PROJECT} or $STIXDB_VIBE_PROJECT)",
    )
    parser.add_argument(
        "--memory-path",
        default=DEFAULT_MEMORY_PATH,
        dest="memory_path",
        help=f"Path to the memory store (default: {DEFAULT_MEMORY_PATH} or $STIXDB_VIBE_PATH)",
    )
    return parser


# ── Demo — run without arguments ──────────────────────────────────────────────

async def demo() -> None:
    """
    Full demonstration of the vibecoding memory workflow.
    Simulates two agents (a planner and a coder) sharing the same memory,
    then a third agent restoring context from scratch.
    """
    print("=" * 60)
    print("  StixDB Vibecoding — Shared Memory Demo")
    print("=" * 60)
    print()

    memory_path = "./vibecode_demo_memory"
    project     = "demo_project"

    # ── Agent 1: Planner ──────────────────────────────────────────────────────
    print("[ Agent 1: Planner ] Writing project spec into shared memory...\n")

    async with VibecodeMemory(project=project, memory_path=memory_path) as mem:
        await mem.store_decision("Frontend: Next.js 14 with App Router")
        await mem.store_decision("Backend: tRPC with Zod validation — no raw REST endpoints")
        await mem.store_decision("Auth: NextAuth.js with JWT stored in httpOnly cookies, never localStorage")
        await mem.store_decision("Database: PostgreSQL via Prisma ORM")
        await mem.store_decision("State management: Zustand — no Redux")
        await mem.store_progress("Planner completed spec. Coder should start with auth flow.")
        print("  Planner stored 5 decisions + progress note.")

    print()

    # ── Agent 2: Coder ────────────────────────────────────────────────────────
    print("[ Agent 2: Coder ] Restoring context before writing code...\n")

    async with VibecodeMemory(project=project, memory_path=memory_path) as mem:

        # Coder restores full context before touching any file
        ctx = await mem.restore_context()
        print(ctx)
        print()

        # Coder writes code and stores what they built + bugs found
        await mem.store_pattern("All tRPC procedures live in src/server/routers/ — one file per domain")
        await mem.store_pattern("Zod schemas are co-located with the router that uses them, not in a separate types/ folder")
        await mem.store_bug(
            "Prisma Client not regenerated after schema change causes runtime type errors. "
            "Fix: always run `npx prisma generate` after editing schema.prisma"
        )
        await mem.store_progress("Coder completed auth router and user router. Dashboard components next.")
        print("\n  Coder stored 2 patterns, 1 bug fix, 1 progress update.")

    print()

    # ── Agent 3: Reviewer (or new session) ───────────────────────────────────
    print("[ Agent 3: Reviewer / New Session ] Cold-starting with full context...\n")

    async with VibecodeMemory(project=project, memory_path=memory_path) as mem:

        # Ask targeted questions — simulates a code reviewer checking conventions
        print("  Asking: 'How does auth work?'")
        ans = await mem.ask("How does authentication work in this project?")
        print(f"  {ans}")
        print()

        print("  Asking: 'Any Prisma gotchas to watch out for?'")
        ans = await mem.ask("Are there any Prisma bugs or gotchas I should know about?")
        print(f"  {ans}")
        print()

        # Final status
        print(await mem.status())

    print()
    print("=" * 60)
    print("  All three agents shared the same memory without any")
    print("  manual handoff. Memory path:", memory_path)
    print("=" * 60)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) == 1:
        # No arguments — run the demo
        asyncio.run(demo())
    else:
        parser = build_parser()
        args = parser.parse_args()
        asyncio.run(cli_main(args))

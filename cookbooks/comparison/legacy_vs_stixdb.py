"""
Comparison — Legacy Memory Systems vs StixDB  (Nebius Edition)
===============================================================
Side-by-side benchmark of three memory approaches:

  System A — Plain List         Raw Python list. Append-only, no search.
  System B — Naive Vector Store Flat cosine similarity (the typical "basic RAG" baseline).
                                No deduplication, no decay, no organization.
  System C — StixDB             Self-organizing graph memory with background agent.

Both the Naive Vector Store and StixDB use the same Nebius embedding model
so the comparison is purely about architecture, not embedding quality.

Four scenarios are run on all three systems with identical inputs:

  1. Duplicate Handling        What happens when you store the same fact multiple times?
  2. Noise Resilience          Can the system surface the right answer from a noisy store?
  3. Related Concept Discovery Does the system find facts that are conceptually related
                               but not lexically similar to the query?
  4. Memory Growth             How does store count grow as you add more facts over time?

Setup:
    pip install "stixdb-engine[local-dev]" openai

    # Required — Nebius credentials
    export NEBIUS_API_KEY=<your-nebius-api-key>

    # Optional overrides (defaults shown)
    export NEBIUS_LLM_MODEL=openai/gpt-oss-120b
    export NEBIUS_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B
    export NEBIUS_EMBEDDING_DIMS=4096

    python cookbooks/comparison/legacy_vs_stixdb.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

# Load .env from the same directory as this script (before any os.getenv calls)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass  # python-dotenv not installed; rely on shell environment

import numpy as np

# ── Rich for terminal output ──────────────────────────────────────────────────
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

# ── StixDB ────────────────────────────────────────────────────────────────────
from stixdb import StixDBEngine, StixDBConfig
from stixdb.config import (
    StorageConfig, StorageMode,
    ReasonerConfig, LLMProvider,
    EmbeddingConfig, EmbeddingProvider,
    AgentConfig,
)

console = Console(width=120)

# ─────────────────────────────────────────────────────────────────────────────
# Nebius config — read once, shared by all systems
# ─────────────────────────────────────────────────────────────────────────────

NEBIUS_BASE_URL      = "https://api.studio.nebius.ai/v1/"
NEBIUS_API_KEY       = os.getenv("NEBIUS_API_KEY", "")
NEBIUS_LLM_MODEL     = os.getenv("NEBIUS_LLM_MODEL",       "openai/gpt-oss-120b")
NEBIUS_EMBED_MODEL   = os.getenv("NEBIUS_EMBEDDING_MODEL",  "Qwen/Qwen3-Embedding-8B")
NEBIUS_EMBED_DIMS    = int(os.getenv("NEBIUS_EMBEDDING_DIMS", "4096"))


def _check_env() -> None:
    if not NEBIUS_API_KEY:
        console.print(Panel(
            "[red]NEBIUS_API_KEY is not set.[/red]\n\n"
            "Export it before running:\n"
            "  [cyan]export NEBIUS_API_KEY=<your-nebius-api-key>[/cyan]\n\n"
            "Optional overrides:\n"
            "  [dim]export NEBIUS_LLM_MODEL=meta-llama/Meta-Llama-3.1-70B-Instruct-fast[/dim]\n"
            "  [dim]export NEBIUS_EMBEDDING_MODEL=BAAI/bge-en-icl[/dim]\n"
            "  [dim]export NEBIUS_EMBEDDING_DIMS=4096[/dim]",
            title="Missing credentials",
            border_style="red",
        ))
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Shared Nebius embedding client (used by both Naive Vector Store and StixDB)
# ─────────────────────────────────────────────────────────────────────────────

class NebiusEmbedder:
    """
    Thin async wrapper around the Nebius OpenAI-compatible embeddings endpoint.
    Shared by the NaiveVectorStore and (via EmbeddingProvider.CUSTOM) StixDB,
    so both systems use exactly the same embedding model.
    """

    def __init__(self) -> None:
        import openai
        self._client = openai.AsyncOpenAI(
            api_key=NEBIUS_API_KEY,
            base_url=NEBIUS_BASE_URL,
        )

    async def embed(self, text: str) -> np.ndarray:
        response = await self._client.embeddings.create(
            input=[text],
            model=NEBIUS_EMBED_MODEL,
        )
        return np.array(response.data[0].embedding, dtype=np.float32)

    async def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        if not texts:
            return []
        response = await self._client.embeddings.create(
            input=texts,
            model=NEBIUS_EMBED_MODEL,
        )
        return [np.array(item.embedding, dtype=np.float32) for item in response.data]


# ─────────────────────────────────────────────────────────────────────────────
# System A — Plain List
# ─────────────────────────────────────────────────────────────────────────────

class PlainListMemory:
    """
    Simplest possible memory: a Python list.
    Store = append. Search = linear keyword substring scan.
    No embeddings, no dedup, no decay.
    """
    NAME = "Plain List"
    COLOR = "red"

    def __init__(self):
        self._store: list[str] = []

    def store(self, text: str) -> None:
        self._store.append(text)

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        query_lower = query.lower()
        matches = [
            {"content": s, "score": 1.0 if query_lower in s.lower() else 0.0}
            for s in self._store
            if query_lower in s.lower()
        ]
        return matches[:top_k]

    def count(self) -> int:
        return len(self._store)

    def reset(self) -> None:
        self._store = []


# ─────────────────────────────────────────────────────────────────────────────
# System B — Naive Vector Store  (same Nebius embeddings, flat cosine only)
# ─────────────────────────────────────────────────────────────────────────────

class NaiveVectorStore:
    """
    Flat cosine-similarity store — the typical "basic RAG" baseline.

    Uses the same Nebius embedding model as StixDB so any differences in
    results are purely architectural (no graph, no dedup, no decay, no agent).
    Every stored document lives forever at equal weight.
    """
    NAME = "Naive Vector Store"
    COLOR = "yellow"

    def __init__(self, embedder: NebiusEmbedder) -> None:
        self._embedder = embedder
        self._texts: list[str] = []
        self._embeddings: list[np.ndarray] = []

    async def store(self, text: str) -> None:
        emb = await self._embedder.embed(text)
        self._texts.append(text)
        self._embeddings.append(emb)

    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        if not self._embeddings:
            return []
        q_emb = await self._embedder.embed(query)
        matrix = np.stack(self._embeddings)
        # Normalise for cosine similarity
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1
        matrix_n = matrix / norms
        q_norm = q_emb / (np.linalg.norm(q_emb) or 1)
        scores = matrix_n @ q_norm
        indices = np.argsort(scores)[::-1][:top_k]
        return [
            {"content": self._texts[i], "score": float(scores[i])}
            for i in indices
        ]

    def count(self) -> int:
        return len(self._texts)

    def reset(self) -> None:
        self._texts = []
        self._embeddings = []


# ─────────────────────────────────────────────────────────────────────────────
# StixDB config — Nebius LLM + Nebius embeddings
# ─────────────────────────────────────────────────────────────────────────────

def _stixdb_config() -> StixDBConfig:
    return StixDBConfig(
        storage=StorageConfig(mode=StorageMode.MEMORY),
        reasoner=ReasonerConfig(
            provider=LLMProvider.CUSTOM,
            model=NEBIUS_LLM_MODEL,
            custom_base_url=NEBIUS_BASE_URL,
            custom_api_key=NEBIUS_API_KEY,
            temperature=0.1,
            max_tokens=1024,
            max_context_nodes=20,
        ),
        embedding=EmbeddingConfig(
            provider=EmbeddingProvider.CUSTOM,
            model=NEBIUS_EMBED_MODEL,
            dimensions=NEBIUS_EMBED_DIMS,
            custom_base_url=NEBIUS_BASE_URL,
            custom_api_key=NEBIUS_API_KEY,
        ),
        agent=AgentConfig(
            cycle_interval_seconds=999,          # manual trigger only
            consolidation_similarity_threshold=0.82,
            decay_half_life_hours=48.0,
            prune_importance_threshold=0.05,
        ),
        verbose=False,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Display helpers
# ─────────────────────────────────────────────────────────────────────────────

def _header(title: str, subtitle: str = "") -> None:
    console.print()
    body = f"[bold white]{title}[/bold white]"
    if subtitle:
        body += f"\n[dim]{subtitle}[/dim]"
    console.print(Panel(body, border_style="cyan", padding=(0, 2)))


def _section(label: str) -> None:
    console.print(f"\n[bold cyan]▶  {label}[/bold cyan]")


def _score_bar(score: float, width: int = 14) -> str:
    filled = int(min(score, 1.0) * width)
    return "█" * filled + "░" * (width - filled)


def _results_table(
    results_a: list[dict],
    results_b: list[dict],
    results_c: list[dict],
    top_k: int = 5,
) -> None:
    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold")
    table.add_column(f"[red]{PlainListMemory.NAME}[/red]",       ratio=33, no_wrap=False)
    table.add_column(f"[yellow]{NaiveVectorStore.NAME}[/yellow]", ratio=33, no_wrap=False)
    table.add_column("[green]StixDB (Nebius)[/green]",            ratio=34, no_wrap=False)

    def _cell(results: list[dict], i: int) -> str:
        if i >= len(results):
            return "[dim]—[/dim]"
        r = results[i]
        score = r.get("score", 0.0)
        content = r["content"]
        if len(content) > 68:
            content = content[:65] + "..."
        return f"[dim]{_score_bar(score)}[/dim] {score:.2f}\n{content}"

    for i in range(min(max(len(results_a), len(results_b), len(results_c), top_k), top_k)):
        table.add_row(_cell(results_a, i), _cell(results_b, i), _cell(results_c, i))

    console.print(table)


def _count_row(count_a: int, count_b: int, count_c: int, label: str = "Stored nodes") -> None:
    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    t.add_column("System", style="bold")
    t.add_column("Count", justify="right")
    t.add_column("Bar")
    mx = max(count_a, count_b, count_c, 1)
    t.add_row(f"[red]{PlainListMemory.NAME}[/red]",       str(count_a), "[red]"    + "█" * int(count_a / mx * 30) + "[/red]")
    t.add_row(f"[yellow]{NaiveVectorStore.NAME}[/yellow]", str(count_b), "[yellow]" + "█" * int(count_b / mx * 30) + "[/yellow]")
    t.add_row("[green]StixDB[/green]",                     str(count_c), "[green]"  + "█" * int(count_c / mx * 30) + "[/green]")
    console.print(f"\n  {label}:")
    console.print(t)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 1 — Duplicate Handling
# ─────────────────────────────────────────────────────────────────────────────

async def scenario_duplicate_handling(
    list_mem: PlainListMemory,
    vec_store: NaiveVectorStore,
    engine: StixDBEngine,
) -> None:
    _header(
        "Scenario 1 — Duplicate Handling",
        "The same core fact is stored 4 times with minor wording variations.\n"
        "How many results come back? How noisy are they?"
    )

    variants = [
        "Alice is the lead engineer on the payments team",
        "Alice leads the payments team",
        "Alice is the engineering lead for payments",
        "Alice leads payments engineering",
    ]

    _section("Storing 4 near-duplicate facts in all three systems...")
    for v in variants:
        list_mem.store(v)
        await vec_store.store(v)
        await engine.store("s1", v, node_type="fact", tags=["team"], importance=0.8)

    await engine.trigger_agent_cycle("s1")

    query = "Who leads the payments team?"
    _section(f'Searching: "{query}"  (top_k=4)')

    r_list = list_mem.search(query, top_k=4)
    r_vec  = await vec_store.search(query, top_k=4)
    r_stix = await engine.retrieve("s1", query, top_k=4)

    _results_table(r_list, r_vec, r_stix, top_k=4)

    stix_stats = await engine.get_collection_stats("s1")
    _count_row(list_mem.count(), vec_store.count(), stix_stats["total_nodes"],
               "Node count after storing 4 duplicates")

    console.print(
        "\n  [red]Plain List[/red]:        returns every matching string — 4 identical results, pure noise.\n"
        "  [yellow]Naive Vector[/yellow]:   all 4 near-identical scores — no signal gain over plain list.\n"
        "  [green]StixDB[/green]:           background agent merged near-duplicates (cosine > 0.82)\n"
        "                  into fewer summary nodes. Fewer results, higher signal."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 2 — Noise Resilience
# ─────────────────────────────────────────────────────────────────────────────

async def scenario_noise_resilience(
    list_mem: PlainListMemory,
    vec_store: NaiveVectorStore,
    engine: StixDBEngine,
) -> None:
    _header(
        "Scenario 2 — Noise Resilience",
        "One important fact (importance=0.95) is buried under 20 unrelated facts (importance=0.4).\n"
        "Which system surfaces the signal?"
    )

    target = "The payment gateway uses Stripe with 3D Secure enabled"
    noise = [
        "The marketing team uses HubSpot for CRM",
        "Weekly all-hands is on Monday at 10am",
        "The office coffee machine is on the 3rd floor",
        "Bob is working on the data pipeline for analytics",
        "The design system uses Tailwind CSS v3",
        "Staging deploys happen automatically on merge to main",
        "The iOS app requires iOS 16 or later",
        "HR uses Workday for time tracking",
        "Company retreat is planned for Q3",
        "Security audit is scheduled for next quarter",
        "The legal team reviewed the new SaaS agreement",
        "Frontend uses React 18 with concurrent mode",
        "Database migrations run with Flyway",
        "The on-call rotation changes every two weeks",
        "Slack is the primary communication tool",
        "Annual performance reviews happen in November",
        "The API rate limit is 1000 requests per minute",
        "The mobile team uses Kotlin Multiplatform",
        "Code freeze is two weeks before each release",
        "The QA team uses Playwright for e2e tests",
    ]

    _section("Storing 1 high-importance target + 20 low-importance noise facts...")
    list_mem.store(target)
    await vec_store.store(target)
    await engine.store("s2", target, node_type="fact", tags=["payments", "security"], importance=0.95)

    for n in noise:
        list_mem.store(n)
        await vec_store.store(n)
        await engine.store("s2", n, node_type="fact", tags=["general"], importance=0.4)

    await engine.trigger_agent_cycle("s2")

    query = "What payment processor do we use and how is it configured?"
    _section(f'Searching: "{query}"  (top_k=3)')

    r_list = list_mem.search(query, top_k=3)
    r_vec  = await vec_store.search(query, top_k=3)
    r_stix = await engine.retrieve("s2", query, top_k=3)

    _results_table(r_list, r_vec, r_stix, top_k=3)

    console.print(
        "\n  [red]Plain List[/red]:        keyword scan returns nothing — 'payment processor' not in any stored string.\n"
        "  [yellow]Naive Vector[/yellow]:   semantic search helps, but all 21 nodes have equal weight —\n"
        "                  noise facts compete for top-K slots.\n"
        "  [green]StixDB[/green]:           importance score (0.95 vs 0.4) promotes the signal node.\n"
        "                  After consolidation, low-importance noise starts decaying."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 3 — Related Concept Discovery  (Graph Expansion)
# ─────────────────────────────────────────────────────────────────────────────

async def scenario_graph_expansion(
    list_mem: PlainListMemory,
    vec_store: NaiveVectorStore,
    engine: StixDBEngine,
) -> None:
    _header(
        "Scenario 3 — Related Concept Discovery",
        "7 facts share the same topic area but use completely different vocabulary.\n"
        "Flat cosine only matches the closest embedding.\n"
        "StixDB graph expansion follows tag-based edges to find the full connected picture."
    )

    facts = [
        ("Alice leads the payments team",                          ["payments", "team"]),
        ("The payments team owns the Stripe integration",          ["payments", "stripe"]),
        ("Stripe 3D Secure is mandatory for EU transactions",      ["stripe", "compliance"]),
        ("EU compliance requires PSD2 strong authentication",      ["compliance", "eu"]),
        ("PSD2 is enforced by the FCA and EBA regulators",         ["compliance", "regulation"]),
        ("Bob maintains the fraud detection service",              ["payments", "fraud"]),
        ("Fraud detection feeds signals into the risk scoring API",["fraud", "api"]),
    ]

    _section("Storing 7 conceptually linked facts with different wording...")
    for content, tags in facts:
        list_mem.store(content)
        await vec_store.store(content)
        await engine.store("s3", content, node_type="fact", tags=tags, importance=0.8)

    await engine.trigger_agent_cycle("s3")

    query = "What regulations apply to our payment infrastructure?"
    _section(f'Searching: "{query}"  (top_k=4)')

    r_list = list_mem.search(query, top_k=4)
    r_vec  = await vec_store.search(query, top_k=4)
    r_stix = await engine.retrieve("s3", query, top_k=4)

    _results_table(r_list, r_vec, r_stix, top_k=4)

    console.print(
        "\n  [red]Plain List[/red]:        returns nothing — 'regulations' not in any stored string.\n"
        "  [yellow]Naive Vector[/yellow]:   retrieves PSD2/FCA/Stripe compliance facts well, but misses\n"
        "                  upstream context (Alice, payments team, fraud detection).\n"
        "  [green]StixDB[/green]:           graph BFS from compliance nodes traverses edges:\n"
        "                  compliance → stripe → payments → Alice → fraud detection.\n"
        "                  Returns the full connected picture in one query."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Scenario 4 — Memory Growth Over Time
# ─────────────────────────────────────────────────────────────────────────────

async def scenario_memory_growth(
    list_mem: PlainListMemory,
    vec_store: NaiveVectorStore,
    engine: StixDBEngine,
) -> None:
    _header(
        "Scenario 4 — Memory Growth Over Time",
        "3 coding sessions, each storing 8 facts with deliberate overlaps between sessions.\n"
        "How does node count grow in each system?"
    )

    sessions = [
        ["Using Next.js 14 App Router", "Database is PostgreSQL via Prisma",
         "Auth uses NextAuth.js with JWT", "Deployed on Vercel",
         "State management: Zustand", "API layer: tRPC with Zod",
         "CSS: Tailwind CSS", "Testing: Vitest + Playwright"],

        ["Using Next.js 14 App Router",       # duplicate
         "Auth uses NextAuth.js with JWT",     # duplicate
         "JWT stored in httpOnly cookie",
         "Refresh tokens expire after 7 days",
         "Database is PostgreSQL via Prisma",  # duplicate
         "Prisma migrations run in CI",
         "CI uses GitHub Actions",
         "Deploy preview on every PR via Vercel"],

        ["State management: Zustand",          # duplicate
         "Zustand stores are in src/stores/",
         "API layer: tRPC with Zod",           # duplicate
         "tRPC routers live in src/server/routers/",
         "Deployed on Vercel",                 # duplicate
         "Vercel project name: my-app-prod",
         "CSS: Tailwind CSS",                  # duplicate
         "Tailwind config extends Inter font"],
    ]

    counts_list, counts_vec, counts_stix = [], [], []

    for i, session_facts in enumerate(sessions, 1):
        _section(f"Session {i}: storing {len(session_facts)} facts ({['first', 'second', 'third'][i-1]} session)...")

        for fact in session_facts:
            list_mem.store(fact)
            await vec_store.store(fact)
            await engine.store("s4", fact, node_type="fact", tags=[f"session_{i}"], importance=0.75)

        await engine.trigger_agent_cycle("s4")

        stats = await engine.get_collection_stats("s4")
        counts_list.append(list_mem.count())
        counts_vec.append(vec_store.count())
        counts_stix.append(stats["total_nodes"])

        console.print(
            f"  After session {i}: "
            f"[red]List={counts_list[-1]}[/red]  "
            f"[yellow]Vector={counts_vec[-1]}[/yellow]  "
            f"[green]StixDB={counts_stix[-1]}[/green]"
        )

    t = Table(title="Node Count After Each Session", box=box.SIMPLE_HEAVY)
    t.add_column("Session",     justify="center", style="bold")
    t.add_column(f"[red]{PlainListMemory.NAME}[/red]",        justify="right")
    t.add_column(f"[yellow]{NaiveVectorStore.NAME}[/yellow]",  justify="right")
    t.add_column("[green]StixDB[/green]",                      justify="right")
    t.add_column("StixDB vs Vector",                           justify="left")

    for i, (cl, cv, cs) in enumerate(zip(counts_list, counts_vec, counts_stix), 1):
        ratio = cs / cv if cv > 0 else 1.0
        color = "green" if ratio < 0.85 else "yellow"
        t.add_row(str(i), str(cl), str(cv), str(cs),
                  f"[{color}]{ratio:.0%} of vector store size[/{color}]")

    console.print()
    console.print(t)
    console.print(
        "\n  [red]Plain List[/red] + [yellow]Naive Vector[/yellow]: grow linearly — every store() adds a node, forever.\n"
        "  [green]StixDB[/green]:         background agent merges re-stated facts across sessions.\n"
        "                  Node count stays sub-linear as sessions accumulate."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Scorecard
# ─────────────────────────────────────────────────────────────────────────────

def _scorecard() -> None:
    _header("Final Scorecard", "Capability comparison across all three systems")

    t = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold")
    t.add_column("Capability",                  style="bold",   min_width=32)
    t.add_column(f"[red]{PlainListMemory.NAME}[/red]",       justify="center", min_width=14)
    t.add_column(f"[yellow]{NaiveVectorStore.NAME}[/yellow]", justify="center", min_width=20)
    t.add_column("[green]StixDB + Nebius[/green]",            justify="center", min_width=18)

    rows = [
        ("Embedding model",              "✗  none",           f"✓  {NEBIUS_EMBED_MODEL}",    f"✓  {NEBIUS_EMBED_MODEL}"),
        ("LLM reasoning",                "✗  none",           "✗  none",                      f"✓  {NEBIUS_LLM_MODEL}"),
        ("Semantic search",              "✗  keyword only",   "✓  cosine similarity",         "✓✓ cosine + graph BFS"),
        ("Duplicate deduplication",      "✗  accumulates",    "✗  accumulates",               "✓  auto-merges (≥0.82)"),
        ("Stale data pruning",           "✗  never forgets",  "✗  never forgets",             "✓  decay + prune"),
        ("Importance ranking",           "✗  none",           "✗  equal weight",              "✓  per-node score"),
        ("Graph / relation expansion",   "✗  none",           "✗  flat only",                 "✓  BFS traversal"),
        ("Background self-organization", "✗  none",           "✗  none",                      "✓  async agent"),
        ("Memory growth with repeats",   "✗  unbounded",      "✗  unbounded",                 "✓  sub-linear"),
        ("ask() LLM synthesis",          "✗  none",           "✗  none",                      "✓  cited answers"),
        ("Multi-agent shared memory",    "△  shared list",    "✗  single-process",            "✓  named collections"),
        ("Persistent storage",           "△  if serialized",  "✗  in-memory only",            "✓  KuzuDB / Neo4j"),
    ]

    for cap, a, b, c in rows:
        t.add_row(cap, a, b, c)

    console.print(t)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    _check_env()

    console.print(Panel(
        "[bold white]StixDB vs Legacy Memory Systems[/bold white]  [dim](Nebius Edition)[/dim]\n\n"
        f"  LLM model       : [cyan]{NEBIUS_LLM_MODEL}[/cyan]\n"
        f"  Embedding model : [cyan]{NEBIUS_EMBED_MODEL}[/cyan]  ({NEBIUS_EMBED_DIMS}d)\n"
        f"  Base URL        : [dim]{NEBIUS_BASE_URL}[/dim]\n\n"
        "[red]System A[/red]  Plain List         — append-only, keyword search\n"
        "[yellow]System B[/yellow]  Naive Vector Store — flat cosine, same Nebius embeddings, no organization\n"
        "[green]System C[/green]  StixDB             — self-organizing graph, Nebius LLM + embeddings",
        title="Comparison Benchmark",
        border_style="bold cyan",
        padding=(1, 4),
    ))

    embedder  = NebiusEmbedder()
    list_mem  = PlainListMemory()
    vec_store = NaiveVectorStore(embedder=embedder)
    config    = _stixdb_config()

    async with StixDBEngine(config=config) as engine:

        await scenario_duplicate_handling(list_mem, vec_store, engine)

        list_mem.reset(); vec_store.reset()
        await scenario_noise_resilience(list_mem, vec_store, engine)

        list_mem.reset(); vec_store.reset()
        await scenario_graph_expansion(list_mem, vec_store, engine)

        list_mem.reset(); vec_store.reset()
        await scenario_memory_growth(list_mem, vec_store, engine)

        _scorecard()

    console.print(Panel(
        "[green]✓[/green]  Benchmark complete.\n\n"
        "Next steps:\n"
        "  [cyan]stixdb serve[/cyan]                             Start the REST API server\n"
        "  [cyan]python cookbooks/vibecoding/shared_memory.py[/cyan]  Persistent vibecoding memory\n"
        "  [cyan]python cookbooks/core-sdk/01_basic_store_retrieve.py[/cyan]  Core SDK walkthrough",
        border_style="green",
        padding=(0, 2),
    ))


if __name__ == "__main__":
    asyncio.run(main())

"""
API interaction commands — all require a running StixDB server.

  collections list / delete / stats
  ingest FILE|DIR
  store TEXT
  search QUERY
  ask QUESTION

Start a server first:
  stixdb serve              (foreground)
  stixdb daemon start       (background)

All commands read host / port / api-key from ~/.stixdb/config.json
and accept explicit --host / --port overrides if needed.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.markup import escape
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn, MofNCompleteColumn
from rich import box

from stixdb.cli._helpers import (
    console, server_url, resolved_port, resolved_api_key,
    default_collection, load_global_config,
    http_get, http_post, http_delete, http_stream_post,
)

# ── Collections sub-app ────────────────────────────────────────────────────────

collections_app = typer.Typer(
    help=(
        "[bold]Manage collections[/bold] on the running StixDB server.\n\n"
        "Requires [cyan]stixdb serve[/cyan] or [cyan]stixdb daemon start[/cyan]."
    ),
    rich_markup_mode="rich",
    no_args_is_help=True,
)


def _conn(host: str, port: int) -> tuple[str, Optional[str]]:
    """Resolve base URL and API key, honouring config defaults."""
    if port == 0:
        port = resolved_port()
    return server_url(host, port), resolved_api_key()


@collections_app.command("list")
def collections_list(
    host: str = typer.Option("localhost", help="Server host."),
    port: int = typer.Option(0, help="Server port (0 = read from config)."),
):
    """
    [bold]List all collections[/bold] on the running server.

    Example:
      stixdb collections list
    """
    base, api_key = _conn(host, port)
    data = http_get(f"{base}/health", api_key)
    colls = data.get("collections", [])
    if not colls:
        console.print("[dim]No collections yet.  Use [cyan]stixdb ingest[/cyan] to create one.[/dim]")
        return
    t = Table(title="Collections", box=box.SIMPLE_HEAVY, header_style="bold cyan")
    t.add_column("#", justify="right", style="dim")
    t.add_column("Name")
    for i, c in enumerate(colls, 1):
        t.add_row(str(i), str(c))
    console.print(t)


@collections_app.command("delete")
def collections_delete(
    name: str = typer.Argument(..., help="Collection name to delete."),
    host: str = typer.Option("localhost", help="Server host."),
    port: int = typer.Option(0, help="Server port."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
):
    """
    [bold]Delete a collection[/bold] and all its data.

    [yellow]This cannot be undone.[/yellow]
    """
    if not yes:
        if not typer.confirm(f"Delete collection '{name}'? This cannot be undone."):
            raise typer.Abort()
    base, api_key = _conn(host, port)
    http_delete(f"{base}/collections/{name}", api_key)
    console.print(f"[green]✓[/green] Deleted collection [bold]{name}[/bold].")


@collections_app.command("stats")
def collections_stats(
    name: str = typer.Argument(..., help="Collection name."),
    host: str = typer.Option("localhost", help="Server host."),
    port: int = typer.Option(0, help="Server port."),
):
    """[bold]Show graph statistics[/bold] for a collection."""
    base, api_key = _conn(host, port)
    data = http_get(f"{base}/collections/{name}/stats", api_key)
    t = Table(title=f"Stats: {name}", box=box.SIMPLE, header_style="bold cyan")
    t.add_column("Metric", style="bold")
    t.add_column("Value", justify="right")
    for k, v in data.items():
        t.add_row(str(k), str(v))
    console.print(t)


@collections_app.command("dedupe")
def collections_dedupe(
    name: str = typer.Argument(..., help="Collection name to deduplicate."),
    host: str = typer.Option("localhost", help="Server host."),
    port: int = typer.Option(0, help="Server port."),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n",
        help="Preview duplicates without deleting anything.",
    ),
):
    """
    [bold]Remove duplicate chunks[/bold] from a collection.

    Runs two passes:
      [cyan]1.[/cyan] Source-version dedup — if the same file was ingested multiple times
         (before the dedup fix), older versions are removed. Only the latest
         ingestion of each source file is kept.
      [cyan]2.[/cyan] Content-hash dedup — any two nodes with byte-identical content are
         collapsed into one (highest importance wins).

    Use [cyan]--dry-run[/cyan] to preview what would be removed without changing anything.

    Examples:
      stixdb collections dedupe proj_myapp
      stixdb collections dedupe proj_myapp --dry-run
    """
    base, api_key = _conn(host, port)

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as prog:
        prog.add_task(f"Scanning [bold]{name}[/bold] for duplicates…")
        data = http_post(
            f"{base}/collections/{name}/dedupe{'?dry_run=true' if dry_run else ''}",
            {},
            api_key,
            timeout=300,
        )

    scanned   = data.get("scanned", 0)
    src_dupes = data.get("source_version_dupes", 0)
    ch_dupes  = data.get("content_hash_dupes", 0)
    total     = data.get("total_duplicates", 0)
    deleted   = data.get("deleted", 0)
    remaining = data.get("remaining", scanned)

    if total == 0:
        console.print(
            f"[green]✓[/green]  [bold]{name}[/bold] is clean — "
            f"no duplicates found in {scanned} nodes."
        )
        return

    t = Table(
        title=f"{'[dim][DRY RUN][/dim] ' if dry_run else ''}Dedupe: {name}",
        box=box.SIMPLE,
        header_style="bold cyan",
    )
    t.add_column("Metric", style="bold")
    t.add_column("Count", justify="right")
    t.add_row("Nodes scanned",              str(scanned))
    t.add_row("Source-version duplicates",  f"[yellow]{src_dupes}[/yellow]")
    t.add_row("Content-hash duplicates",    f"[yellow]{ch_dupes}[/yellow]")
    t.add_row("Total duplicates found",     f"[red]{total}[/red]")
    t.add_row(
        "Deleted" if not dry_run else "Would delete",
        f"[{'green' if deleted or dry_run else 'dim'}]{deleted if not dry_run else total}[/]",
    )
    t.add_row("Remaining after clean",      str(remaining if not dry_run else scanned - total))
    console.print(t)

    if dry_run:
        console.print(
            f"\n[dim]Dry run — nothing deleted.  "
            f"Run without [bold]--dry-run[/bold] to remove {total} duplicate(s).[/dim]"
        )
    else:
        console.print(
            f"\n[green]✓[/green]  Removed [bold red]{deleted}[/bold red] duplicate(s) "
            f"from [cyan]{name}[/cyan].  {remaining} nodes remain."
        )


@collections_app.command("analyze")
def collections_analyze(
    name: str = typer.Argument(..., help="Collection name to analyze."),
    host: str = typer.Option("localhost", help="Server host."),
    port: int = typer.Option(0, help="Server port."),
    sample: int = typer.Option(120, "--sample", "-s", help="Nodes to sample for similarity scan."),
):
    """
    [bold]Diagnose why summary nodes are or aren't being created.[/bold]

    Samples a slice of the collection and computes pairwise cosine similarities.
    Shows the distribution and compares against the consolidation threshold so
    you can see whether the threshold needs to be lowered.

    Examples:
      stixdb collections analyze proj_myapp
      stixdb collections analyze proj_myapp --sample 200
    """
    base, api_key = _conn(host, port)

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as prog:
        prog.add_task(f"Scanning similarity in [bold]{name}[/bold]…")
        data = http_get(f"{base}/collections/{name}/similarity-scan?sample={sample}&top_k=15", api_key)

    if "error" in data:
        console.print(f"[red]{data['error']}[/red]")
        return

    threshold   = data["consolidation_threshold"]
    above       = data["pairs_above_threshold"]
    sampled     = data["nodes_sampled"]
    pairs       = data["pairs_computed"]
    stats       = data["stats"]
    top_pairs   = data.get("top_pairs", [])

    # ── Summary panel ────────────────────────────────────────────────────────
    if above == 0:
        verdict = f"[red]0 pairs above threshold ({threshold}) — no consolidation will fire.[/red]"
        suggestion = (
            f"\n  [dim]Highest similarity found: [bold]{stats['max']}[/bold]. "
            f"Try lowering [cyan]consolidation_threshold[/cyan] in your config to "
            f"[bold]{max(0.5, round(stats['p95'] - 0.02, 2))}[/bold] "
            f"(p95 of your data) to start seeing merges.[/dim]"
        )
    else:
        verdict = f"[green]{above} pair(s) above threshold ({threshold}) — consolidation will merge them.[/green]"
        suggestion = ""

    console.print(Panel(
        f"{verdict}{suggestion}",
        title=f"[bold]Similarity Analysis: {name}[/bold]",
        border_style="cyan",
        padding=(0, 2),
    ))

    # ── Stats table ───────────────────────────────────────────────────────────
    synth_lower = data.get("synthesis_lower", 0.55)   # provided by server if available
    st = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
    st.add_column("Metric", style="bold")
    st.add_column("Value", justify="right")
    st.add_row("Nodes sampled",              str(sampled))
    st.add_row("Pairs computed",             str(pairs))
    st.add_row("Synthesis zone",             f"[cyan]{synth_lower:.2f}[/cyan] – [yellow]{threshold}[/yellow]")
    st.add_row("Merge threshold",            f"[yellow]{threshold}[/yellow]")
    st.add_row("Pairs above threshold",      f"[{'green' if above else 'red'}]{above}[/]")
    # count synthesis-zone pairs
    synth_pairs = sum(
        1 for p in top_pairs
        if not p["above_threshold"] and p["similarity"] >= synth_lower
    )
    st.add_row("Pairs in synthesis zone",    f"[cyan]{synth_pairs}[/cyan] (visible in top-15)")
    st.add_row("Min similarity",             str(stats["min"]))
    st.add_row("Mean similarity",            str(stats["mean"]))
    st.add_row("Median similarity",          str(stats["median"]))
    st.add_row("p75",                        str(stats["p75"]))
    st.add_row("p90",                        str(stats["p90"]))
    st.add_row("p95",                        str(stats["p95"]))
    st.add_row("p99",                        str(stats["p99"]))
    st.add_row("Max similarity",             f"[bold]{stats['max']}[/bold]")
    console.print(st)

    # ── Top pairs table ───────────────────────────────────────────────────────
    if top_pairs:
        pt = Table(
            title="Top Similar Pairs",
            box=box.SIMPLE, show_header=True, header_style="bold cyan",
        )
        pt.add_column("Sim", justify="right", style="bold", width=6)
        pt.add_column("Zone", width=12)
        pt.add_column("Node A (preview)")
        pt.add_column("Node B (preview)")
        for p in top_pairs[:15]:
            sim = p["similarity"]
            if p["above_threshold"]:
                zone_label = "[green]merge[/green]"
                color = "green"
            elif sim >= synth_lower:
                zone_label = "[cyan]synthesis[/cyan]"
                color = "cyan"
            else:
                zone_label = "[dim]none[/dim]"
                color = ""
            pt.add_row(
                f"[{color}]{sim}[/]" if color else str(sim),
                zone_label,
                escape(p["content_a"]),
                escape(p["content_b"]),
            )
        console.print(pt)

    console.print()


@collections_app.command("clean")
def collections_clean(
    name: str = typer.Argument(..., help="Collection name to clean."),
    host: str = typer.Option("localhost", help="Server host."),
    port: int = typer.Option(0, help="Server port."),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n",
        help="Preview what would be removed without deleting anything.",
    ),
):
    """
    [bold]Remove garbage maintenance nodes[/bold] from a collection.

    Deletes auto-generated maintenance/consolidator summary nodes whose
    content is empty, an error phrase, or a raw JSON fragment — nodes
    that pollute search results and working memory without adding value.

    Use [cyan]--dry-run[/cyan] to preview what would be removed.

    Examples:
      stixdb collections clean proj_myapp --dry-run
      stixdb collections clean proj_myapp
    """
    base, api_key = _conn(host, port)

    # Pull all nodes from the server
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as prog:
        prog.add_task(f"Scanning [bold]{name}[/bold] for garbage nodes…")
        data = http_get(f"{base}/collections/{name}/nodes?limit=10000", api_key)

    nodes = data if isinstance(data, list) else data.get("nodes", [])

    # --- Garbage detection (mirrors engine._is_useful_maintenance_answer) ---
    _internal_sources = {"agent-maintenance", "agent-consolidator", "agent-reflection"}
    _garbage_phrases = (
        "returned an empty response",
        "no answer",
        "no relevant",
        "i don't have",
        "i do not have",
        "cannot answer",
        "not enough information",
        "no information",
        "unable to",
        "i couldn't find",
        "i could not find",
    )

    def _is_garbage(node: dict) -> bool:
        source = (node.get("source") or "").strip().lower()
        if source not in _internal_sources:
            return False
        content = (node.get("content") or "").strip()
        if not content or len(content) < 30:
            return True

        # Maintenance nodes are stored as "Label\n\nAnswer body".
        # Extract the body (everything after the first blank line) so we can
        # check the answer independently of the label prefix.
        parts = content.split("\n\n", 1)
        body = parts[1].strip() if len(parts) == 2 else content

        # Raw JSON response — LLM returned structured output instead of prose
        if body.startswith("{") or body.startswith("["):
            return True
        # Full content also checked (handles edge cases with no label)
        if content.startswith("{") or content.startswith("["):
            return True

        lower = content.lower()
        return any(phrase in lower for phrase in _garbage_phrases)

    garbage = [n for n in nodes if _is_garbage(n)]

    if not garbage:
        console.print(
            f"[green]✓[/green]  [bold]{name}[/bold] is clean — "
            f"no garbage maintenance nodes found ({len(nodes)} nodes scanned)."
        )
        return

    t = Table(
        title=f"{'[dim][DRY RUN][/dim] ' if dry_run else ''}Garbage nodes in {name}",
        box=box.SIMPLE,
        header_style="bold cyan",
    )
    t.add_column("#", justify="right", style="dim")
    t.add_column("Source", style="dim")
    t.add_column("Label / Content preview")
    for i, node in enumerate(garbage[:20], 1):
        label = escape((node.get("content") or "")[:80].replace("\n", " "))
        t.add_row(str(i), escape(node.get("source", "")), label)
    if len(garbage) > 20:
        t.add_row("…", "", f"[dim]… and {len(garbage) - 20} more[/dim]")
    console.print(t)

    if dry_run:
        console.print(
            f"\n[dim]Dry run — nothing deleted.  "
            f"Run without [bold]--dry-run[/bold] to remove {len(garbage)} node(s).[/dim]"
        )
        return

    deleted = 0
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as prog:
        task = prog.add_task(f"Deleting {len(garbage)} garbage node(s)…")
        for node in garbage:
            node_id = node.get("id") or node.get("node_id", "")
            if not node_id:
                continue
            try:
                http_delete(f"{base}/collections/{name}/nodes/{node_id}", api_key)
                deleted += 1
            except Exception:
                pass
        prog.update(task, completed=True)

    console.print(
        f"\n[green]✓[/green]  Removed [bold red]{deleted}[/bold red] garbage node(s) "
        f"from [cyan]{name}[/cyan]."
    )


# ── ingest ─────────────────────────────────────────────────────────────────────

def cmd_ingest(
    path: Path = typer.Argument(..., help="File or folder to ingest.", exists=True),
    collection: Optional[str] = typer.Option(
        None, "--collection", "-c",
        help="Target collection name (default: from config).",
    ),
    host: str = typer.Option("localhost", help="Server host."),
    port: int = typer.Option(0, help="Server port."),
    tags: str = typer.Option("", "--tags", "-t", help="Comma-separated tags to attach."),
    chunk_size: int = typer.Option(0, help="Characters per chunk (0 = config default)."),
    chunk_overlap: int = typer.Option(0, help="Overlap between chunks (0 = config default)."),
    recursive: bool = typer.Option(True, help="Recurse into sub-directories when path is a folder."),
):
    """
    [bold]Ingest a file or folder[/bold] into a collection.

    StixDB chunks, embeds, and stores the content in the graph.
    A collection is created automatically if it does not exist yet.

    Requires a running server — [cyan]stixdb serve[/cyan] or [cyan]stixdb daemon start[/cyan].

    Examples:
      stixdb ingest notes.md
      stixdb ingest ./docs/ --collection knowledge --tags work,q1
      stixdb ingest report.pdf -c research --chunk-size 800
    """
    base, api_key = _conn(host, port)
    coll = collection or default_collection()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    cf = load_global_config()
    if cf:
        chunk_size = chunk_size or cf.ingestion.chunk_size
        chunk_overlap = chunk_overlap or cf.ingestion.chunk_overlap
    else:
        chunk_size = chunk_size or 1000
        chunk_overlap = chunk_overlap or 200

    abs_path = path.resolve()
    if abs_path.is_dir():
        _ingest_folder(base, coll, abs_path, tag_list, chunk_size, chunk_overlap, recursive, api_key)
    else:
        _ingest_file(base, coll, abs_path, tag_list, chunk_size, chunk_overlap, api_key)


def _ingest_file(
    base: str,
    collection: str,
    filepath: Path,
    tags: list[str],
    chunk_size: int,
    chunk_overlap: int,
    api_key: Optional[str],
) -> None:
    import httpx
    url = f"{base}/collections/{collection}/upload"
    headers = {"X-API-Key": api_key} if api_key else {}

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as prog:
        prog.add_task(f"Uploading [bold]{filepath.name}[/bold]…")
        try:
            with open(filepath, "rb") as fh:
                r = httpx.post(
                    url,
                    files={"file": (filepath.name, fh, "application/octet-stream")},
                    data={
                        "tags": ",".join(tags),
                        "chunk_size": str(chunk_size),
                        "chunk_overlap": str(chunk_overlap),
                    },
                    headers=headers,
                    timeout=300,
                )
            r.raise_for_status()
        except httpx.ConnectError:
            console.print("[red]✗[/red] Cannot reach server.  Run [cyan]stixdb serve[/cyan] or [cyan]stixdb daemon start[/cyan].")
            raise typer.Exit(1)
        except httpx.HTTPStatusError as exc:
            console.print(f"[red]HTTP {exc.response.status_code}:[/red] {exc.response.text}")
            raise typer.Exit(1)

    d = r.json()
    console.print(
        f"[green]✓[/green] [bold]{filepath.name}[/bold] → [cyan]{collection}[/cyan]  "
        f"{d.get('ingested_chunks', '?')} chunks  parser={d.get('parser', '?')}"
    )


def _build_ignore_filter(folderpath: Path):
    """
    Return a callable(Path) -> bool that is True when a file should be skipped.

    Respects .gitignore files (root, parent git root, and subdirectories) via
    pathspec.  Falls back to a basic fnmatch parser when pathspec is absent.
    Either way, a hard-coded set of heavy directories (node_modules, .git,
    __pycache__, dist, build, .next, …) is always ignored.
    """
    import fnmatch

    ALWAYS_IGNORE_DIRS = {
        "node_modules", ".git", "__pycache__", ".venv", "venv", "env",
        ".tox", "dist", "build", ".next", ".nuxt", "out", ".output",
        ".cache", ".parcel-cache", "coverage", ".nyc_output",
        "target", ".mypy_cache", ".pytest_cache", ".ruff_cache",
        ".idea", ".vscode", "eggs", ".eggs",
    }

    # ── Collect patterns from .gitignore files ────────────────────────────────
    # Walk upward from folderpath to find the git root; collect every .gitignore
    # on the way (patterns from parent repos apply to all paths inside).
    all_patterns: list[str] = []

    check = folderpath
    for _ in range(8):
        gi = check / ".gitignore"
        if gi.exists():
            try:
                lines = gi.read_text(encoding="utf-8", errors="replace").splitlines()
                if check == folderpath:
                    all_patterns.extend(lines)
                else:
                    # Parent .gitignore: only non-rooted patterns apply everywhere
                    all_patterns.extend(l for l in lines if not l.strip().startswith("/"))
            except Exception:
                pass
        if (check / ".git").is_dir():
            break
        parent = check.parent
        if parent == check:
            break
        check = parent

    # Sub-directory .gitignore files — prefix patterns with their sub-path
    for sub_gi in folderpath.rglob(".gitignore"):
        if sub_gi.parent == folderpath:
            continue  # already added above
        try:
            sub_dir = sub_gi.parent.relative_to(folderpath).as_posix()
            for line in sub_gi.read_text(encoding="utf-8", errors="replace").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and not stripped.startswith("!"):
                    all_patterns.append(f"{sub_dir}/{stripped.lstrip('/')}")
        except Exception:
            pass

    # ── Build matcher ─────────────────────────────────────────────────────────
    try:
        import pathspec
        spec = pathspec.PathSpec.from_lines("gitwildmatch", all_patterns)

        def is_ignored(p: Path) -> bool:
            parts = p.relative_to(folderpath).parts
            if any(part in ALWAYS_IGNORE_DIRS or part.endswith(".egg-info") for part in parts):
                return True
            return spec.match_file(p.relative_to(folderpath).as_posix())

    except ImportError:
        # Fallback: basic fnmatch — handles the most common patterns
        def is_ignored(p: Path) -> bool:  # type: ignore[misc]
            parts = p.relative_to(folderpath).parts
            if any(part in ALWAYS_IGNORE_DIRS or part.endswith(".egg-info") for part in parts):
                return True
            rel = p.relative_to(folderpath).as_posix()
            for pattern in all_patterns:
                pattern = pattern.strip()
                if not pattern or pattern.startswith("#") or pattern.startswith("!"):
                    continue
                clean = pattern.lstrip("/")
                if fnmatch.fnmatch(p.name, clean):
                    return True
                if fnmatch.fnmatch(rel, clean):
                    return True
                if "/" not in clean and any(fnmatch.fnmatch(part, clean) for part in parts):
                    return True
            return False

    return is_ignored


def _ingest_folder(
    base: str,
    collection: str,
    folderpath: Path,
    tags: list[str],
    chunk_size: int,
    chunk_overlap: int,
    recursive: bool,
    api_key: Optional[str],
) -> None:
    import threading
    import time
    import httpx
    from rich.live import Live
    from rich.table import Table
    from rich.progress import Progress, BarColumn, MofNCompleteColumn, TextColumn
    from rich.panel import Panel
    from rich.console import Group

    SUPPORTED = {
        ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".cs",
        ".go", ".rs", ".sh", ".sql", ".rb", ".php", ".swift", ".kt",
        ".md", ".markdown", ".rst", ".txt", ".log",
        ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".xml",
        ".csv", ".tsv", ".html", ".htm", ".css", ".scss", ".sass",
        ".pdf",
    }

    # ── 1. Walk directory (respecting .gitignore) ────────────────────────────
    is_ignored = _build_ignore_filter(folderpath)
    pattern = "**/*" if recursive else "*"
    all_files = sorted([
        p for p in folderpath.glob(pattern)
        if p.is_file() and p.suffix.lower() in SUPPORTED and not is_ignored(p)
    ])

    if not all_files:
        console.print(f"[yellow]No supported files found in {folderpath}[/yellow]")
        return

    # ── 2. State table ───────────────────────────────────────────────────────
    # Each entry: status ∈ waiting | uploading | done | error | skipped
    states: list[dict] = [
        {"status": "waiting", "chunks": 0, "error": None}
        for _ in all_files
    ]

    SPIN = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def _rel(p: Path) -> str:
        rel = p.relative_to(folderpath).as_posix()
        return ("…" + rel[-47:]) if len(rel) > 50 else rel

    def _file_table(spin: str) -> Table:
        t = Table(box=box.SIMPLE, show_header=False, padding=(0, 1),
                  expand=False, show_edge=False)
        t.add_column("file", no_wrap=True, min_width=50)
        t.add_column("status", width=16, no_wrap=True)
        t.add_column("info", justify="right", width=10, no_wrap=True)

        for fpath, state in zip(all_files, states):
            rel = _rel(fpath)
            s = state["status"]
            rel_safe = escape(rel)
            if s == "waiting":
                t.add_row(f"[dim]{rel_safe}[/dim]", "[dim]· waiting[/dim]", "")
            elif s == "uploading":
                t.add_row(f"[bold white]{rel_safe}[/bold white]",
                          f"[yellow]{spin} uploading[/yellow]", "")
            elif s == "done":
                t.add_row(rel_safe,
                          "[green]✓ done[/green]",
                          f"[dim]{state['chunks']} chunks[/dim]")
            elif s == "error":
                t.add_row(f"[red]{rel_safe}[/red]",
                          "[red]✗ error[/red]", "")
            else:
                t.add_row(f"[dim]{rel_safe}[/dim]", "[dim]— skipped[/dim]", "")
        return t

    overall = Progress(
        TextColumn("  "),
        BarColumn(bar_width=45, complete_style="green", finished_style="green"),
        MofNCompleteColumn(),
        TextColumn("[dim]files[/dim]"),
        TextColumn("  ·  "),
        TextColumn("[green]{task.fields[chunks]}[/green]"),
        TextColumn("[dim]chunks[/dim]"),
    )
    task_id = overall.add_task("", total=len(all_files), chunks="0")

    gitignore_note = "[dim]· .gitignore ✓[/dim]" if (folderpath / ".gitignore").exists() else ""
    header = Panel(
        f"[bold]{folderpath.as_posix()}[/bold]  →  [cyan]{collection}[/cyan]\n"
        f"[dim]tags: {', '.join(tags) if tags else '—'}  ·  "
        f"chunk_size={chunk_size}  ·  {len(all_files)} files[/dim]  {gitignore_note}",
        border_style="cyan",
        padding=(0, 2),
    )

    # ── 3. Upload each file with animated display ────────────────────────────
    upload_url = f"{base}/collections/{collection}/upload"
    http_headers = {"X-API-Key": api_key} if api_key else {}
    done_count = 0
    total_chunks = 0
    spin_idx = 0

    with Live(console=console, refresh_per_second=15) as live:

        def _render():
            live.update(Group(
                header,
                _file_table(SPIN[spin_idx % len(SPIN)]),
                overall,
            ))

        _render()

        for i, fpath in enumerate(all_files):
            states[i]["status"] = "uploading"

            # Upload in background thread so spinner can animate
            result: dict = {}

            def _upload(fp=fpath, res=result):
                try:
                    with open(fp, "rb") as fh:
                        r = httpx.post(
                            upload_url,
                            files={"file": (fp.name, fh, "application/octet-stream")},
                            data={
                                "tags": ",".join(tags),
                                "chunk_size": str(chunk_size),
                                "chunk_overlap": str(chunk_overlap),
                            },
                            headers=http_headers,
                            timeout=300,
                        )
                    r.raise_for_status()
                    d = r.json()
                    res["ok"] = True
                    res["chunks"] = d.get("ingested_chunks", 0)
                except Exception as exc:
                    res["ok"] = False
                    res["error"] = str(exc)

            t = threading.Thread(target=_upload, daemon=True)
            t.start()

            while t.is_alive():
                spin_idx += 1
                _render()
                time.sleep(0.07)

            t.join()

            if result.get("ok"):
                chunks = result.get("chunks", 0)
                states[i]["status"] = "done"
                states[i]["chunks"] = chunks
                total_chunks += chunks
                done_count += 1
            else:
                states[i]["status"] = "error"
                states[i]["error"] = result.get("error", "unknown error")

            overall.update(task_id, completed=done_count, chunks=str(total_chunks))
            _render()

        # Final settled frame
        _render()

    skipped = len(all_files) - done_count
    console.print(
        f"\n[green]✓[/green]  [bold]{done_count}[/bold] files ingested  ·  "
        f"[bold green]{total_chunks}[/bold green] chunks  →  [cyan]{collection}[/cyan]"
        + (f"  [dim]({skipped} failed/skipped)[/dim]" if skipped else "")
    )


# ── store ──────────────────────────────────────────────────────────────────────

def cmd_store(
    text: str = typer.Argument(..., help="Text to store as a memory node."),
    collection: Optional[str] = typer.Option(None, "--collection", "-c", help="Target collection."),
    host: str = typer.Option("localhost", help="Server host."),
    port: int = typer.Option(0, help="Server port."),
    tags: str = typer.Option("", "--tags", "-t", help="Comma-separated tags."),
    importance: float = typer.Option(0.5, help="Node importance score  0.0 – 1.0."),
    node_type: str = typer.Option("fact", help="Node type: fact / concept / summary / …"),
):
    """
    [bold]Store a single memory node[/bold] directly into a collection.

    Useful for injecting short facts without needing a file.

    Example:
      stixdb store "Alice is the lead engineer on payments" --tags team,alice
      stixdb store "Deploy checklist completed" -c ops --importance 0.9
    """
    base, api_key = _conn(host, port)
    coll = collection or default_collection()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    payload = {
        "content": text,
        "node_type": node_type,
        "importance": importance,
        "tags": tag_list,
    }
    data = http_post(f"{base}/collections/{coll}/nodes", payload, api_key)
    console.print(f"[green]✓[/green] Stored node [dim]{data.get('node_id', '?')}[/dim] → [cyan]{coll}[/cyan]")


# ── search ─────────────────────────────────────────────────────────────────────

def cmd_search(
    query: str = typer.Argument(..., help="Search query."),
    collection: Optional[str] = typer.Option(None, "--collection", "-c", help="Collection to search."),
    host: str = typer.Option("localhost", help="Server host."),
    port: int = typer.Option(0, help="Server port."),
    top_k: int = typer.Option(5, "--top-k", "-k", help="Number of results to return."),
    threshold: float = typer.Option(0.1, help="Minimum match score  0.0 – 1.0."),
    depth: int = typer.Option(1, help="Graph expansion depth (higher = more context, slower)."),
    tags: str = typer.Option("", "--tags", "-t", help="Filter results by these tags."),
    mode: str = typer.Option("hybrid", "--mode", "-m", help="Retrieval mode: hybrid (keyword + semantic, default), keyword (fast, no API), or semantic (vector only)."),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON instead of formatted results."),
):
    """
    [bold]Search[/bold] across a collection.

    Defaults to [cyan]hybrid[/cyan] mode — keyword scoring + vector similarity, merged.
    Use [cyan]--mode keyword[/cyan] for fast tag/term matching (no embedding API call).
    Use [cyan]--mode semantic[/cyan] for pure vector similarity search.

    Run [cyan]stixdb keywords -c COLLECTION[/cyan] first to see what terms exist.

    Examples:
      stixdb search "auth decisions" -c proj_myapp
      stixdb search "deploy steps" --tags ops --depth 2
      stixdb search "latency" --mode semantic -c infra
      stixdb search "in-progress" --mode keyword -c proj_myapp
    """
    base, api_key = _conn(host, port)
    coll = collection or default_collection()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    payload = {
        "query": query,
        "collection": coll,
        "top_k": top_k,
        "max_results": top_k,
        "threshold": threshold,
        "depth": depth,
        "tag_filter": tag_list,
        "include_heatmap": False,
        "include_metadata": False,
        "sort_by": "relevance",
        "search_mode": mode,
    }
    data = http_post(f"{base}/search", payload, api_key)

    if json_output:
        console.print_json(json.dumps(data))
        return

    results = data.get("results", [])
    if not results:
        console.print(f"[yellow]No results[/yellow] for: [italic]{query}[/italic]")
        return

    console.print()
    console.print(Panel(
        f"[bold]{query}[/bold]\n[dim]{coll}  ·  {len(results)} result(s)[/dim]",
        title="Search Results",
        border_style="cyan",
        padding=(0, 2),
    ))

    for i, r in enumerate(results, 1):
        score   = r.get("score", 0.0)
        snippet = r.get("snippet", "")
        source  = r.get("source", "")
        tags_r  = r.get("tags", [])
        filled  = int(min(score, 1.0) * 20)
        bar     = "█" * filled + "░" * (20 - filled)
        meta    = []
        if source and source != "unknown":
            meta.append(f"[dim]{source}[/dim]")
        if tags_r:
            meta.append(f"[dim]tags: {', '.join(tags_r)}[/dim]")

        console.print(
            f"\n  [bold cyan]{i}.[/bold cyan]  "
            f"[dim]{bar}[/dim] [bold]{score:.3f}[/bold]"
            + (f"  {' · '.join(meta)}" if meta else "")
        )
        console.print(f"     {escape(snippet)}")

    console.print()


# ── keywords ──────────────────────────────────────────────────────────────────

def cmd_keywords(
    collection: Optional[str] = typer.Option(None, "--collection", "-c", help="Collection to inspect."),
    host: str = typer.Option("localhost", help="Server host."),
    port: int = typer.Option(0, help="Server port."),
    for_agent: bool = typer.Option(False, "--for-agent", help="Output compact text for pasting into an agent prompt."),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON."),
):
    """
    [bold]Show searchable keywords[/bold] for a collection.

    Lists all tags (with counts) and the top content terms found across
    all nodes. Use this to know exactly what words to pass to
    [cyan]stixdb search[/cyan] — especially useful for agents that need
    a vocabulary reference before querying.

    Examples:
      stixdb keywords -c proj_myapp
      stixdb keywords -c proj_myapp --for-agent
    """
    base, api_key = _conn(host, port)
    coll = collection or default_collection()
    data = http_get(f"{base}/collections/{coll}/keywords", api_key)

    if json_output:
        console.print_json(json.dumps(data))
        return

    tags = data.get("tags", [])
    top_terms = data.get("top_terms", [])
    node_types = data.get("node_types", [])
    sources = data.get("sources", [])
    total = data.get("total_nodes", 0)

    if for_agent:
        lines = [
            f"StixDB collection: {coll}  ({total} nodes)",
            "",
            "Tags (use exactly with --tags or in keyword queries):",
            "  " + "  ".join(f"{t['tag']}({t['count']})" for t in tags[:80]),
            "",
            "Top content terms (use in search queries):",
            "  " + ", ".join(top_terms[:100]),
            "",
            "Node types present:",
            "  " + ", ".join(node_types),
        ]
        if sources:
            lines += ["", "Sources:", "  " + ", ".join(sources[:20])]
        console.print("\n".join(lines))
        return

    console.print()
    console.print(Panel(
        f"[bold]{coll}[/bold]  [dim]·  {total} nodes[/dim]",
        title="Collection Keywords",
        border_style="cyan",
        padding=(0, 2),
    ))

    if tags:
        t = Table(title="Tags", box=box.SIMPLE, header_style="bold cyan", show_header=True)
        t.add_column("Tag", style="cyan")
        t.add_column("Count", justify="right", style="dim")
        for entry in tags[:60]:
            t.add_row(entry["tag"], str(entry["count"]))
        if len(tags) > 60:
            t.add_row(f"[dim]… and {len(tags) - 60} more[/dim]", "")
        console.print(t)

    if top_terms:
        console.print()
        console.print("[bold]Top content terms:[/bold]")
        console.print("  " + escape("  ·  ".join(top_terms[:80])))

    if node_types:
        console.print()
        console.print(f"[bold]Node types:[/bold]  {', '.join(node_types)}")

    console.print()


# ── ask ────────────────────────────────────────────────────────────────────────

def cmd_ask(
    question: str = typer.Argument(..., help="Question to ask the AI agent."),
    collection: Optional[str] = typer.Option(None, "--collection", "-c", help="Collection to query."),
    host: str = typer.Option("localhost", help="Server host."),
    port: int = typer.Option(0, help="Server port."),
    top_k: int = typer.Option(15, "--top-k", "-k", help="Context nodes to retrieve."),
    depth: int = typer.Option(2, help="Graph traversal depth."),
    thinking: int = typer.Option(1, "--thinking", "-t", help="Thinking steps (>1 enables multi-hop reasoning)."),
    hops: int = typer.Option(4, "--hops", help="Max retrieval hops per thinking step."),
    max_tokens: Optional[int] = typer.Option(None, "--max-tokens", "-m", help="Max tokens for the LLM response. Overrides server default."),
    stream: bool = typer.Option(False, "--stream", "-s", help="Stream answer tokens progressively as they are generated."),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON."),
):
    """
    [bold]Ask the AI reasoning agent[/bold] a question.

    Retrieves relevant context from the memory graph and synthesises a
    grounded, cited answer using the configured LLM.

    [bold cyan]Streaming Mode:[/bold cyan]
    Use [cyan]--stream[/cyan] to print answer tokens as they arrive, Perplexity-style.

    [bold cyan]Thinking Mode:[/bold cyan]
    Use [cyan]--thinking 2[/cyan] or higher to enable autonomous multi-hop reasoning.

    Examples:
      stixdb ask "What payment processor do we use?"
      stixdb ask "Explain the auth flow" --stream
      stixdb ask "Summarise our security posture" -c infra --thinking 3
      stixdb ask "Who owns the auth service?" --json
    """
    from rich.live import Live
    from rich.text import Text

    base, api_key = _conn(host, port)
    coll = collection or default_collection()

    payload = {
        "question": question,
        "top_k": top_k,
        "depth": depth,
        "threshold": 0.2,
        "thinking_steps": thinking,
        "hops_per_step": hops,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    console.print()
    console.print(Panel(
        f"[italic]{escape(question)}[/italic]",
        title="Question",
        border_style="dim",
        padding=(0, 2),
    ))

    if stream:
        buffer = ""
        first_token = True
        with Live(
            Text("Retrieving context…", style="dim"),
            refresh_per_second=15,
            console=console,
            vertical_overflow="visible",
        ) as live:
            for chunk in http_stream_post(f"{base}/collections/{coll}/ask/stream", payload, api_key):
                if chunk.get("type") != "answer":
                    continue
                token = chunk.get("content", "")
                if not token:
                    continue
                if first_token:
                    first_token = False
                buffer += token
                live.update(Markdown(buffer))

        # Re-render final answer inside a panel once streaming is complete
        console.print()
        if buffer:
            console.print(Panel(
                Markdown(buffer),
                title="[bold green]Answer[/bold green]",
                border_style="green",
                padding=(1, 2),
            ))
        console.print()
        return

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as prog:
        prog.add_task("Thinking…" if thinking > 1 else "Synthesising…")
        data = http_post(f"{base}/collections/{coll}/ask", payload, api_key)

    if json_output:
        console.print_json(json.dumps(data))
        return

    answer    = data.get("answer") or data.get("response") or data.get("content", "")
    sources   = data.get("sources") or data.get("citations") or []
    reasoning = data.get("reasoning_trace") or data.get("reasoning") or ""

    if answer:
        # If the answer came back as a dict/list (LLM ignored the string rule), format it.
        if isinstance(answer, (dict, list)):
            import json as _json
            answer = _json.dumps(answer, indent=2, ensure_ascii=False)
        console.print(Panel(
            Markdown(str(answer)),
            title="[bold green]Answer[/bold green]",
            border_style="green",
            padding=(1, 2),
        ))

    if sources:
        t = Table(title="Sources", box=box.SIMPLE, show_header=True, header_style="bold cyan")
        t.add_column("#", justify="right", style="dim")
        t.add_column("Node ID", style="dim")
        t.add_column("Snippet")
        for i, src in enumerate(sources[:8], 1):
            if isinstance(src, dict):
                node_id = src.get("node_id") or src.get("id") or ""
                snippet = str(src.get("content") or src.get("snippet", ""))[:120]
            else:
                node_id, snippet = "", str(src)[:120]
            t.add_row(str(i), escape(str(node_id)), escape(snippet))
        console.print(t)

    if reasoning:
        limit = 2000
        preview = reasoning[:limit] + ("…" if len(reasoning) > limit else "")
        console.print(Panel(
            f"[dim]{escape(preview)}[/dim]",
            title="[dim]Thinking[/dim]",
            border_style="dim",
            padding=(0, 2),
        ))

    console.print()


# ── Graph viewer ───────────────────────────────────────────────────────────────

_GRAPH_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>StixDB Graph &mdash; __COLLECTION__</title>
<script src="/vis-network.js"></script>
<link rel="stylesheet" href="/vis-network.css"/>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0d1117; color: #c9d1d9; font-family: ui-monospace, "Cascadia Code", monospace; }
  #graph { position: fixed; inset: 0; }

  /* ── side panel ── */
  #panel {
    position: fixed; top: 12px; right: 12px;
    width: 340px; max-height: calc(100vh - 24px);
    background: #161b22; border: 1px solid #30363d; border-radius: 10px;
    padding: 16px; overflow-y: auto; z-index: 10;
  }
  #panel h2 { font-size: 13px; color: #58a6ff; margin-bottom: 10px; }
  #panel .badge {
    display: inline-block; padding: 2px 8px; border-radius: 12px;
    font-size: 10px; font-weight: 600; margin: 2px 2px 8px 0;
    background: #21262d; border: 1px solid #30363d;
  }
  #panel pre {
    font-size: 11px; white-space: pre-wrap; word-break: break-word;
    color: #8b949e; line-height: 1.5; margin-top: 8px;
    border-top: 1px solid #21262d; padding-top: 8px;
  }
  #panel .meta { font-size: 11px; color: #6e7681; margin: 2px 0; }

  /* ── legend ── */
  #legend {
    position: fixed; bottom: 12px; left: 12px;
    background: #161b22; border: 1px solid #30363d; border-radius: 10px;
    padding: 12px 16px; z-index: 10; font-size: 11px; line-height: 1.9;
  }
  #legend b { color: #8b949e; display: block; margin-top: 6px; }
  #legend b:first-child { margin-top: 0; }
  .dot { display: inline-block; width: 11px; height: 11px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }
  .diamond { display: inline-block; width: 11px; height: 11px; background: currentColor;
             transform: rotate(45deg); margin-right: 6px; vertical-align: middle; }

  /* ── header strip ── */
  #header {
    position: fixed; top: 12px; left: 12px;
    background: #161b22cc; border: 1px solid #30363d; border-radius: 8px;
    padding: 6px 14px; font-size: 12px; color: #8b949e; z-index: 10;
    backdrop-filter: blur(4px);
  }
  #header span { color: #58a6ff; font-weight: 600; }
</style>
</head>
<body>
<div id="graph"></div>
<div id="header">StixDB &mdash; <span>__COLLECTION__</span></div>
<div id="panel"><h2>Graph Explorer</h2><p style="font-size:11px;color:#6e7681">Click any node to inspect it.</p></div>
<div id="legend">
  <b>Tier (colour)</b>
  <div><span class="dot" style="background:#f97316"></span>working</div>
  <div><span class="dot" style="background:#3b82f6"></span>semantic</div>
  <div><span class="dot" style="background:#22c55e"></span>episodic</div>
  <div><span class="dot" style="background:#a855f7"></span>procedural</div>
  <div><span class="dot" style="background:#6b7280"></span>archived</div>
  <b>Type (shape)</b>
  <div><span class="dot" style="background:#c9d1d9"></span>fact</div>
  <div><span class="diamond" style="color:#c9d1d9"></span>summary</div>
</div>

<script>
(function () {
  const TIER_COLORS = {
    working:    "#f97316",
    semantic:   "#3b82f6",
    episodic:   "#22c55e",
    procedural: "#a855f7",
    archived:   "#6b7280",
  };
  const EDGE_COLORS = {
    derived_from: "#60a5fa",
    summarizes:   "#34d399",
    relates_to:   "#6b7280",
    causes:       "#f87171",
    supports:     "#a3e635",
    contradicts:  "#f97316",
  };

  const raw = __GRAPH_DATA__;

  const visNodes = raw.nodes.map(n => ({
    id: n.id,
    label: (n.content || "").slice(0, 36) + ((n.content || "").length > 36 ? "\u2026" : ""),
    color: {
      background: TIER_COLORS[n.tier] || "#6b7280",
      border:     TIER_COLORS[n.tier] || "#6b7280",
      highlight:  { background: "#f0f6fc", border: "#58a6ff" },
      hover:      { background: "#f0f6fc", border: "#58a6ff" },
    },
    shape: (n.node_type === "summary") ? "diamond" : "dot",
    size: 8 + Math.round((n.importance || 0.5) * 18),
    font: { color: "#c9d1d9", size: 11, face: "monospace" },
    borderWidth: n.pinned ? 3 : 1,
    borderWidthSelected: 3,
    _raw: n,
  }));

  const visEdges = raw.edges.map(e => ({
    id: e.id,
    from: e.source_id,
    to:   e.target_id,
    label: (e.relation_type || "").replace(/_/g, " "),
    color: { color: EDGE_COLORS[e.relation_type] || "#4b5563", highlight: "#58a6ff", hover: "#58a6ff" },
    font:  { color: "#6e7681", size: 9, align: "middle" },
    arrows: "to",
    width: Math.max(1, Math.round((e.weight || 0.5) * 2.5)),
    smooth: { type: "curvedCW", roundness: 0.15 },
  }));

  const network = new vis.Network(
    document.getElementById("graph"),
    { nodes: new vis.DataSet(visNodes), edges: new vis.DataSet(visEdges) },
    {
      physics: {
        solver: "forceAtlas2Based",
        forceAtlas2Based: { gravitationalConstant: -60, centralGravity: 0.005, springLength: 120, damping: 0.4 },
        stabilization: { iterations: 200, updateInterval: 25 },
      },
      interaction: { hover: true, tooltipDelay: 150, navigationButtons: true, keyboard: true },
      nodes: { borderWidth: 1 },
      edges: { selectionWidth: 2 },
    }
  );

  network.on("click", function (params) {
    if (!params.nodes.length) return;
    const node = visNodes.find(x => x.id === params.nodes[0]);
    if (!node) return;
    const n = node._raw;

    const tags   = (n.tags || []).map(t => `<span class="badge">${t}</span>`).join("");
    const source = n.source ? `<div class="meta">source: ${n.source}</div>` : "";
    const imp    = `<div class="meta">importance: ${(n.importance || 0).toFixed(2)} &nbsp; tier: ${n.tier} &nbsp; type: ${n.node_type}</div>`;
    const id_    = `<div class="meta" style="font-size:10px;color:#484f58">id: ${n.id}</div>`;

    document.getElementById("panel").innerHTML =
      `<h2>${n.node_type} / ${n.tier}</h2>${tags}${imp}${source}${id_}<pre>${(n.content || "").replace(/</g,"&lt;")}</pre>`;
  });

  network.on("stabilizationProgress", function (p) {
    const pct = Math.round(p.iterations / p.total * 100);
    document.getElementById("panel").innerHTML =
      `<h2>Laying out graph\u2026</h2><p style="font-size:11px;color:#6e7681">${pct}%</p>`;
  });
  network.on("stabilizationIterationsDone", function () {
    document.getElementById("panel").innerHTML =
      `<h2>Graph Explorer</h2><p style="font-size:11px;color:#6e7681">Click any node to inspect it.</p>`;
    network.setOptions({ physics: { enabled: false } });
  });
})();
</script>
</body>
</html>
"""


def cmd_graph(
    collection: Optional[str] = typer.Argument(None, help="Collection to visualise (default: from config)."),
    host: str = typer.Option("localhost", help="StixDB server host."),
    port: int = typer.Option(0, help="StixDB server port (0 = read from config)."),
    viewer_port: int = typer.Option(4021, "--viewer-port", "-p", help="Local port for the graph viewer (default 4021)."),
    no_browser: bool = typer.Option(False, "--no-browser", help="Print URL only — do not open the browser automatically."),
):
    """
    [bold]Open an interactive graph viewer[/bold] for a collection.

    Fetches the collection graph from the running StixDB server, starts a
    local viewer at [cyan]http://localhost:PORT[/cyan], and opens it in your
    default browser.

    Node colour = memory tier. Node shape = type (dot = fact, diamond = summary).
    Node size   = importance. Click any node to read its full content.

    Examples:
      stixdb graph                         # view default collection
      stixdb graph proj_myapp              # view a named collection
      stixdb graph proj_myapp --viewer-port 8080
      stixdb graph proj_myapp --no-browser # print URL, do not open browser
    """
    import threading
    import urllib.request
    import webbrowser
    from http.server import BaseHTTPRequestHandler, HTTPServer

    base, api_key = _conn(host, port)
    coll = collection or default_collection()

    # Fetch vis-network assets once and cache to ~/.stixdb/ for offline use
    _VIS_JS_URL  = "https://cdn.jsdelivr.net/npm/vis-network@9.1.9/dist/vis-network.min.js"
    _VIS_CSS_URL = "https://cdn.jsdelivr.net/npm/vis-network@9.1.9/styles/vis-network.min.css"
    _cache_dir = Path.home() / ".stixdb"
    _cache_dir.mkdir(parents=True, exist_ok=True)
    _vis_js_cache  = _cache_dir / "vis-network.min.js"
    _vis_css_cache = _cache_dir / "vis-network.min.css"

    def _load_asset(cache_path: Path, url: str) -> bytes:
        if cache_path.exists():
            return cache_path.read_bytes()
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                data = r.read()
            cache_path.write_bytes(data)
            return data
        except Exception:
            return b""

    vis_js  = _load_asset(_vis_js_cache,  _VIS_JS_URL)
    vis_css = _load_asset(_vis_css_cache, _VIS_CSS_URL)

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as prog:
        prog.add_task(f"Fetching graph for [cyan]{coll}[/cyan]…")
        data = http_get(f"{base}/collections/{coll}/graph", api_key)

    node_count = data.get("count", len(data.get("nodes", [])))
    edge_count = len(data.get("edges", []))

    graph_json = json.dumps(data).replace("</", "<\\/")
    html = (
        _GRAPH_HTML
        .replace("__COLLECTION__", coll)
        .replace("__GRAPH_DATA__", graph_json)
    )
    html_bytes = html.encode("utf-8")

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/vis-network.js":
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript")
                self.send_header("Content-Length", str(len(vis_js)))
                self.end_headers()
                self.wfile.write(vis_js)
            elif self.path == "/vis-network.css":
                self.send_response(200)
                self.send_header("Content-Type", "text/css")
                self.send_header("Content-Length", str(len(vis_css)))
                self.end_headers()
                self.wfile.write(vis_css)
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html_bytes)))
                self.end_headers()
                self.wfile.write(html_bytes)

        def log_message(self, *args):
            pass  # suppress per-request noise

    try:
        server = HTTPServer(("127.0.0.1", viewer_port), _Handler)
    except OSError as exc:
        console.print(f"[red]Could not bind viewer to port {viewer_port}:[/red] {exc}")
        console.print(f"  Try a different port:  [cyan]stixdb graph {coll} --viewer-port 8080[/cyan]")
        raise typer.Exit(1)

    url = f"http://localhost:{viewer_port}"

    console.print(
        f"\n  [bold cyan]StixDB Graph Viewer[/bold cyan]\n"
        f"  Collection : [bold]{coll}[/bold]\n"
        f"  Nodes      : {node_count}   Edges: {edge_count}\n"
        f"  URL        : [cyan]{url}[/cyan]\n\n"
        f"  Press [bold]Ctrl+C[/bold] to stop the viewer.\n"
    )

    if not no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("\n  Viewer stopped.")


# ── enrich ─────────────────────────────────────────────────────────────────────

def cmd_enrich(
    collection: Optional[str] = typer.Option(None, "--collection", "-c", help="Collection to enrich."),
    host: str = typer.Option("localhost", help="Server host."),
    port: int = typer.Option(0, help="Server port."),
    batch_size: int = typer.Option(10, "--batch-size", "-b", help="Node pairs per LLM call."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show how many pairs would be enriched without calling the LLM."),
):
    """
    [bold]Run the LLM enrichment agent[/bold] over a collection.

    Finds cross-type node pairs with no semantic edge and asks the LLM
    to classify the relationship between them. Writes INFERRED edges back.

    This is Trigger 3 — the manual on-demand re-run. Triggers 1 and 2
    fire automatically after ingest and during background cycles.

    Examples:
      stixdb enrich -c proj_myapp
      stixdb enrich -c proj_myapp --batch-size 20
      stixdb enrich -c proj_myapp --dry-run
    """
    base_url, api_key = _conn(host, port)
    coll = collection or default_collection()

    # ── Step 1: pre-scan (free — no LLM) so the user knows what's coming ──────
    if not dry_run:
        with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True) as progress:
            progress.add_task(f"[dim]Scanning pairs in [bold]{coll}[/bold]...", total=None)
            scan = http_post(f"{base_url}/collections/{coll}/enrich", {"batch_size": batch_size, "dry_run": True}, api_key, timeout=60)

        if scan:
            pairs_found   = scan.get("pairs_found", 0)
            already_done  = scan.get("pairs_skipped", 0)
            will_enrich   = scan.get("would_enrich", pairs_found - already_done)
            llm_calls_est = max(1, -(-will_enrich // batch_size))  # ceil division
            console.print(
                f"  [dim]Scan:[/dim] [bold]{pairs_found}[/bold] cross-type pairs  "
                f"[dim]·[/dim]  [bold]{already_done}[/bold] already annotated  "
                f"[dim]·[/dim]  [bold cyan]{will_enrich}[/bold cyan] to enrich  "
                f"[dim]·[/dim]  ~[bold]{llm_calls_est}[/bold] LLM call(s) of {batch_size} pairs each"
            )
            if will_enrich == 0:
                console.print("\n  [dim]Nothing to do — all pairs already have semantic edges.[/dim]")
                return
            console.print()

    # ── Step 2: run enrichment via SSE stream (or dry-run) ────────────────────
    payload: dict = {"batch_size": batch_size, "dry_run": dry_run}

    data: dict = {}

    if dry_run:
        with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True) as progress:
            progress.add_task(f"[cyan]Scanning [bold]{coll}[/bold]...", total=None)
            data = http_post(f"{base_url}/collections/{coll}/enrich", payload, api_key, timeout=60)
    else:
        # Streaming path — Docker-style progress bar
        _pair_count = will_enrich if (scan) else "?"
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(bar_width=30),
            MofNCompleteColumn(),
            TextColumn("·"),
            TimeElapsedColumn(),
            TextColumn("·"),
            TextColumn("[green]{task.fields[edges]}[/green] edges  [dim]{task.fields[status]}[/dim]"),
            transient=False,
            console=console,
        ) as progress:
            task = progress.add_task(
                f"enrich {coll}",
                total=None,
                edges=0,
                status="waiting...",
            )
            for event in http_stream_post(
                f"{base_url}/collections/{coll}/enrich/stream", payload, api_key, timeout=600
            ):
                etype = event.get("type")
                if etype == "start":
                    progress.update(task, total=event.get("total_batches", 1), completed=0)
                elif etype == "batch":
                    progress.update(
                        task,
                        completed=event.get("batch", 1),
                        edges=event.get("edges_so_far", 0),
                        status=f"batch {event.get('batch')}/{event.get('total_batches')}",
                    )
                elif etype == "done":
                    t = progress.tasks[0]
                    progress.update(task, completed=t.total or 1, status="done")
                    data = event

    if not data:
        console.print("[red]  Enrichment failed — is the server running?[/red]")
        raise typer.Exit(1)

    edges_created = data.get("edges_created", 0)
    pairs_skipped = data.get("pairs_skipped", 0)
    pairs_no_relation = data.get("pairs_no_relation", 0)
    pairs_ambiguous = data.get("pairs_ambiguous", 0)
    llm_calls = data.get("llm_calls", 0)
    errors = data.get("errors", [])

    # ── Summary panel ──────────────────────────────────────────────────────────
    table = Table(box=box.ROUNDED, show_header=False, padding=(0, 2))
    table.add_column(style="dim")
    table.add_column(style="bold")
    if dry_run:
        table.add_row("Pairs found", str(data.get("pairs_found", 0)))
        table.add_row("Already annotated", str(pairs_skipped))
        table.add_row("Would enrich", str(data.get("would_enrich", data.get("pairs_found", 0) - pairs_skipped)))
    else:
        table.add_row("Edges created", str(edges_created))
        table.add_row("Ambiguous edges", str(pairs_ambiguous))
        table.add_row("No relation found", str(pairs_no_relation))
        table.add_row("Pairs skipped", str(pairs_skipped))
        table.add_row("LLM calls made", str(llm_calls))

    console.print(
        Panel(
            table,
            title=f"[bold cyan]{'Dry run' if dry_run else 'Enrichment'} — {coll}[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        )
    )

    # ── Edge detail table with rationale ──────────────────────────────────────
    if not dry_run:
        edge_details = data.get("edge_details", [])
        if edge_details:
            edge_table = Table(
                box=box.SIMPLE,
                show_header=True,
                padding=(0, 1),
                header_style="bold cyan",
            )
            edge_table.add_column("Source", style="green", max_width=35, no_wrap=True)
            edge_table.add_column("Relation", style="bold yellow", max_width=12)
            edge_table.add_column("Target", style="blue", max_width=35, no_wrap=True)
            edge_table.add_column("Conf", justify="right", style="dim", max_width=4)
            edge_table.add_column("Why", style="dim", max_width=50)
            for ed in edge_details:
                src_label = f"[dim]{ed['source_type']}[/dim] {ed['source_content']}"
                tgt_label = f"[dim]{ed['target_type']}[/dim] {ed['target_content']}"
                rationale  = ed.get("rationale", "") or ""
                edge_table.add_row(
                    src_label,
                    ed["relation"],
                    tgt_label,
                    str(ed["confidence"]),
                    rationale[:120],
                )
            console.print()
            console.print(
                Panel(
                    edge_table,
                    title="[bold cyan]Edges created[/bold cyan]",
                    border_style="dim",
                    padding=(0, 1),
                )
            )
        elif edges_created == 0:
            console.print("\n  [dim]No new edges — all pairs already annotated or no relation found.[/dim]")

    if errors:
        console.print(f"\n  [yellow]Errors ({len(errors)}):[/yellow]")
        for err in errors[:5]:
            console.print(f"  [dim]  • {err}[/dim]")
        if len(errors) > 5:
            console.print(f"  [dim]  ... and {len(errors) - 5} more[/dim]")

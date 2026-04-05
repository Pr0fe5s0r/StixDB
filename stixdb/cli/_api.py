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
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box

from stixdb.cli._helpers import (
    console, server_url, resolved_port, resolved_api_key,
    default_collection, load_global_config,
    http_get, http_post, http_delete,
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

    # ── 1. Walk directory ────────────────────────────────────────────────────
    pattern = "**/*" if recursive else "*"
    all_files = sorted([
        p for p in folderpath.glob(pattern)
        if p.is_file() and p.suffix.lower() in SUPPORTED
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
            if s == "waiting":
                t.add_row(f"[dim]{rel}[/dim]", "[dim]· waiting[/dim]", "")
            elif s == "uploading":
                t.add_row(f"[bold white]{rel}[/bold white]",
                          f"[yellow]{spin} uploading[/yellow]", "")
            elif s == "done":
                t.add_row(rel,
                          "[green]✓ done[/green]",
                          f"[dim]{state['chunks']} chunks[/dim]")
            elif s == "error":
                t.add_row(f"[red]{rel}[/red]",
                          "[red]✗ error[/red]", "")
            else:
                t.add_row(f"[dim]{rel}[/dim]", "[dim]— skipped[/dim]", "")
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

    header = Panel(
        f"[bold]{folderpath.as_posix()}[/bold]  →  [cyan]{collection}[/cyan]\n"
        f"[dim]tags: {', '.join(tags) if tags else '—'}  ·  "
        f"chunk_size={chunk_size}  ·  {len(all_files)} files[/dim]",
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
    threshold: float = typer.Option(0.25, help="Minimum similarity score  0.0 – 1.0."),
    depth: int = typer.Option(1, help="Graph expansion depth (higher = more context, slower)."),
    tags: str = typer.Option("", "--tags", "-t", help="Filter results by these tags."),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON instead of formatted results."),
):
    """
    [bold]Semantic search[/bold] across a collection.

    Finds the most relevant memory nodes for your query using vector
    similarity plus graph expansion.

    Examples:
      stixdb search "who leads the payments team?"
      stixdb search "security config" -c infra --depth 2 --top-k 10
      stixdb search "deploy steps" --tags ops --json
    """
    base, api_key = _conn(host, port)
    coll = collection or default_collection()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    payload = {
        "query": query,
        "collection": coll,
        "top_k": top_k * 3,
        "max_results": top_k,
        "threshold": threshold,
        "depth": depth,
        "tag_filter": tag_list,
        "include_heatmap": False,
        "include_metadata": False,
        "sort_by": "relevance",
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
        console.print(f"     {snippet}")

    console.print()


# ── ask ────────────────────────────────────────────────────────────────────────

def cmd_ask(
    question: str = typer.Argument(..., help="Question to ask the AI agent."),
    collection: Optional[str] = typer.Option(None, "--collection", "-c", help="Collection to query."),
    host: str = typer.Option("localhost", help="Server host."),
    port: int = typer.Option(0, help="Server port."),
    top_k: int = typer.Option(15, "--top-k", "-k", help="Context nodes to retrieve."),
    depth: int = typer.Option(2, help="Graph traversal depth."),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON."),
):
    """
    [bold]Ask the AI reasoning agent[/bold] a question.

    Retrieves relevant context from the memory graph and synthesises a
    grounded, cited answer using the configured LLM.

    Examples:
      stixdb ask "What payment processor do we use?"
      stixdb ask "Summarise our security posture" -c infra --depth 3
      stixdb ask "Who owns the auth service?" --json
    """
    base, api_key = _conn(host, port)
    coll = collection or default_collection()

    payload = {
        "question": question,
        "top_k": top_k,
        "depth": depth,
        "threshold": 0.2,
    }

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as prog:
        prog.add_task("Thinking…")
        data = http_post(f"{base}/collections/{coll}/ask", payload, api_key)

    if json_output:
        console.print_json(json.dumps(data))
        return

    answer    = data.get("answer") or data.get("response") or data.get("content", "")
    sources   = data.get("sources") or data.get("citations") or []
    reasoning = data.get("reasoning") or ""

    console.print()
    console.print(Panel(
        f"[italic]{question}[/italic]",
        title="Question",
        border_style="dim",
        padding=(0, 2),
    ))

    if answer:
        console.print(Panel(
            answer,
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
                node_id = src.get("id", src.get("node_id", ""))
                snippet = str(src.get("content", src.get("snippet", "")))[:120]
            else:
                node_id, snippet = "", str(src)[:120]
            t.add_row(str(i), node_id, snippet)
        console.print(t)

    if reasoning:
        console.print(Panel(
            f"[dim]{reasoning[:600]}{'…' if len(reasoning) > 600 else ''}[/dim]",
            title="[dim]Reasoning[/dim]",
            border_style="dim",
            padding=(0, 2),
        ))

    console.print()

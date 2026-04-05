"""
init, serve, status, info — all operate on ~/.stixdb/

  init          Configure StixDB globally in ~/.stixdb/config.json
  init --local  Write a project-local .stixdb/config.json instead
  serve         Start the server in the foreground (reads ~/.stixdb/)
  status        Ping the running server and list collections
  info          Show config summary
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer
from rich.panel import Panel
from rich.table import Table
from rich import box

from stixdb.cli._helpers import (
    GLOBAL_DIR, GLOBAL_CONFIG,
    console, load_global_config, server_url, http_get,
    resolved_port, resolved_api_key, require_global_config,
)


def cmd_init(
    local: bool = typer.Option(
        False, "--local", "-l",
        help="Write to [bold].stixdb/config.json[/bold] in CWD instead of ~/.stixdb/.",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing config."),
    dir: Path = typer.Option(
        Path("."), "--dir", "-d",
        help="Directory for --local config (default: CWD).",
    ),
):
    """
    [bold]Configure StixDB.[/bold]

    Runs the interactive wizard and writes the config.

    [bold]Global[/bold] (default) — [bold]~/.stixdb/config.json[/bold]
      One config for your entire machine. [cyan]stixdb serve[/cyan] and
      [cyan]stixdb daemon start[/cyan] read it from any directory.

    [bold]Local[/bold] (--local) — [bold].stixdb/config.json[/bold] in CWD
      Project-specific override. Useful when a project needs its own
      LLM / embedding / storage settings.
    """
    from stixdb.wizard import run_wizard

    if local:
        config_path = dir.resolve() / ".stixdb" / "config.json"
        scope = "project-local"
        next_hint = "stixdb serve"
    else:
        config_path = GLOBAL_CONFIG
        scope = "global  (~/.stixdb/)"
        next_hint = "stixdb serve  [dim]or[/dim]  stixdb daemon start"

    if config_path.exists() and not force:
        console.print(Panel(
            f"Config already exists at [bold]{config_path}[/bold]\n\n"
            "Run with [cyan]--force[/cyan] to overwrite.",
            border_style="yellow",
        ))
        raise typer.Exit(0)

    try:
        cfg = run_wizard(config_path.parent)
        cfg.save(config_path)
        console.print()
        console.print(Panel(
            f"[green]✓[/green] Config saved → [bold]{config_path}[/bold]\n\n"
            f"Next steps:\n"
            f"  [cyan]{next_hint}[/cyan]\n"
            f"  [cyan]stixdb ingest ./docs/[/cyan]         Ingest files\n"
            f"  [cyan]stixdb search \"your query\"[/cyan]    Semantic search\n"
            f"  [cyan]stixdb ask \"your question\"[/cyan]    Ask the AI agent",
            title=f"[green]Setup complete[/green]  ({scope})",
            border_style="green",
            padding=(1, 2),
        ))
    except KeyboardInterrupt:
        console.print("\n[yellow]Setup cancelled.[/yellow]")
        raise typer.Exit(0)


def cmd_serve(
    host: str = typer.Option("0.0.0.0", help="Host to bind."),
    port: int = typer.Option(0, help="Port (0 = read from ~/.stixdb/config.json, default 4020)."),
    reload: bool = typer.Option(False, "--reload", help="Hot-reload — dev mode."),
    log_level: str = typer.Option("info", help="Uvicorn log level."),
):
    """
    [bold]Start StixDB in the foreground.[/bold]

    Reads [bold]~/.stixdb/config.json[/bold] — your collections are available
    from any directory on this machine.

    Ctrl+C to stop.  For a persistent background process:
      [cyan]stixdb daemon start[/cyan]
    """
    import uvicorn
    require_global_config()
    os.environ["STIXDB_PROJECT_DIR"] = str(GLOBAL_DIR.parent)

    try:
        from stixdb.config import ConfigFile
        cf = ConfigFile.load(GLOBAL_CONFIG)
        if port == 0:
            port = cf.server.port
        dh = "localhost" if host == "0.0.0.0" else host
        console.print(Panel(
            f"[bold cyan]StixDB[/bold cyan]\n\n"
            f"  Config      : [dim]{GLOBAL_CONFIG}[/dim]\n"
            f"  LLM         : [cyan]{cf.llm.provider}[/cyan] / [bold]{cf.llm.model}[/bold]\n"
            f"  Embedding   : [cyan]{cf.embedding.provider}[/cyan] / [bold]{cf.embedding.model}[/bold]"
            f"  ({cf.embedding.dimensions}d)\n"
            f"  Storage     : [dim]{cf.storage.path}[/dim]\n"
            f"  Collection  : default=[bold]{cf.default_collection}[/bold]\n\n"
            f"  URL         : [underline]http://{dh}:{port}[/underline]\n"
            f"  Docs        : [underline]http://{dh}:{port}/docs[/underline]\n\n"
            "[dim]Ctrl+C to stop  ·  [cyan]stixdb daemon start[/cyan] runs in background[/dim]",
            title="[bold]stixdb serve[/bold]  (foreground)",
            border_style="bold cyan",
            padding=(1, 2),
        ))
    except Exception as exc:
        console.print(f"[yellow]Warning:[/yellow] Could not parse config: {exc}")
        if port == 0:
            port = int(os.getenv("STIXDB_API_PORT", "4020"))

    uvicorn.run("stixdb.api.server:app", host=host, port=port, reload=reload, log_level=log_level)


def cmd_status(
    host: str = typer.Option("localhost", help="Server host."),
    port: int = typer.Option(0, help="Port (0 = read from config)."),
):
    """
    [bold]Ping the running StixDB server.[/bold]

    Shows whether the server is up and which collections are loaded.
    For the background daemon, use [cyan]stixdb daemon status[/cyan].
    """
    if port == 0:
        port = resolved_port()
    api_key = resolved_api_key()
    base = server_url(host, port)
    data = http_get(f"{base}/health", api_key)
    colls = data.get("collections", [])

    console.print(Panel(
        f"[green]●[/green] Server running at [underline]{base}[/underline]\n"
        f"  Collections: [bold]{len(colls)}[/bold]",
        title="StixDB Status",
        border_style="green",
    ))
    if colls:
        t = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
        t.add_column("#", justify="right", style="dim")
        t.add_column("Collection")
        for i, c in enumerate(colls, 1):
            t.add_row(str(i), str(c))
        console.print(t)


def cmd_info(
    local: bool = typer.Option(False, "--local", help="Show project-local .stixdb/config.json instead."),
    dir: Path = typer.Option(Path("."), "--dir", "-d", help="Project dir for --local."),
):
    """
    [bold]Show engine version and config summary.[/bold]

    Defaults to the global [bold]~/.stixdb/config.json[/bold].
    Use [cyan]--local[/cyan] to inspect a project-local config.
    """
    from stixdb import __version__

    if local:
        config_path = dir.resolve() / ".stixdb" / "config.json"
        scope = f"project  ({dir.resolve() / '.stixdb'})"
    else:
        config_path = GLOBAL_CONFIG
        scope = "global  (~/.stixdb/)"

    t = Table(title="StixDB", box=box.SIMPLE_HEAVY, header_style="bold cyan")
    t.add_column("Property", style="bold", min_width=20)
    t.add_column("Value")
    t.add_row("Version", __version__)
    t.add_row("Docs", "https://github.com/Pr0fe5s0r/StixDB")
    t.add_row("Config scope", scope)

    if config_path.exists():
        try:
            from stixdb.config import ConfigFile
            cf = ConfigFile.load(config_path)
            t.add_row("─" * 20, "─" * 30)
            t.add_row("Config", str(config_path))
            t.add_row("LLM", f"{cf.llm.provider} / {cf.llm.model}  (temp={cf.llm.temperature}, max_tokens={cf.llm.max_tokens})")
            t.add_row("Embedding", f"{cf.embedding.provider} / {cf.embedding.model} ({cf.embedding.dimensions}d)")
            t.add_row("Storage", f"{cf.storage.mode}  →  {cf.storage.path}")
            t.add_row("Chunk size / overlap", f"{cf.ingestion.chunk_size} / {cf.ingestion.chunk_overlap}")
            t.add_row("Agent cycle", f"{cf.agent.cycle_interval}s  (consolidation≥{cf.agent.consolidation_threshold})")
            t.add_row("Observability", f"traces={cf.observability.enable_traces}  metrics={cf.observability.enable_metrics}  log={cf.observability.log_level}")
            t.add_row("Port", str(cf.server.port))
            t.add_row("Default collection", cf.default_collection)
        except Exception as exc:
            t.add_row("Config error", str(exc))
    else:
        hint = "stixdb init --local" if local else "stixdb init"
        t.add_row("Config", f"[yellow]Not found[/yellow] — run [cyan]{hint}[/cyan]")

    console.print()
    console.print(t)
    console.print()

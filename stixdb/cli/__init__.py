"""
StixDB CLI — entry point: stixdb.cli:app

Architecture
────────────
  ~/.stixdb/config.json   Universal config — written by `stixdb init`,
                          read by `stixdb serve` and `stixdb daemon start`
                          from any directory on any machine.

  .stixdb/config.json     Optional project-local override — written by
                          `stixdb init --local`.

Command reference
─────────────────
  SETUP
    stixdb init               Configure ~/.stixdb/config.json  (global, recommended)
    stixdb init --local       Configure .stixdb/config.json in CWD (project override)
    stixdb info               Show active config summary
    stixdb status             Ping the running server

  SERVER  (choose one)
    stixdb serve              Start in the foreground  (Ctrl+C to stop)
    stixdb daemon start       Start as background daemon
    stixdb daemon stop        Stop the daemon
    stixdb daemon restart     Restart the daemon
    stixdb daemon status      Check daemon process + API health
    stixdb daemon logs        View / follow daemon log output

  API  (require a running server)
    stixdb collections list         List all collections
    stixdb collections delete NAME  Delete a collection
    stixdb collections stats  NAME  Graph statistics
    stixdb ingest FILE|DIR          Ingest files into a collection
    stixdb store TEXT               Store a single memory node
    stixdb search QUERY             Semantic search
    stixdb ask QUESTION             Ask the AI reasoning agent
    stixdb enrich -c COLLECTION     Run LLM enrichment agent (on-demand)
"""
from __future__ import annotations

# Load .env early so all sub-modules see environment variables
try:
    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv(usecwd=True))
except ImportError:
    pass

import typer

from stixdb.cli._daemon import daemon_app
from stixdb.cli._api import (
    collections_app,
    cmd_ingest,
    cmd_store,
    cmd_search,
    cmd_keywords,
    cmd_ask,
    cmd_graph,
    cmd_enrich,
)
from stixdb.cli._server import (
    cmd_init,
    cmd_serve,
    cmd_status,
    cmd_info,
    cmd_compact,
)

# ── Main app ───────────────────────────────────────────────────────────────────

app = typer.Typer(
    name="stixdb",
    help=(
        "[bold cyan]StixDB[/bold cyan] — Reasoning Agentic Context Database\n\n"
        "  [bold]One config, everywhere.[/bold]  Run [cyan]stixdb init[/cyan] once and your\n"
        "  database is accessible from any directory on this machine.\n\n"
        "  [bold]Quick start:[/bold]\n"
        "    [cyan]stixdb init[/cyan]                     Configure  (~/.stixdb/)\n"
        "    [cyan]stixdb serve[/cyan]                    Start server  (foreground)\n"
        "    [cyan]stixdb daemon start[/cyan]             Start server  (background)\n"
        "    [cyan]stixdb ingest ./docs/[/cyan]           Ingest files into a collection\n"
        "    [cyan]stixdb search \"my query\"[/cyan]        Semantic search\n"
        "    [cyan]stixdb ask \"my question\"[/cyan]        Ask the AI agent\n\n"
        "  [dim]Use [cyan]stixdb init --local[/cyan] for a project-specific config override.[/dim]"
    ),
    rich_markup_mode="rich",
    no_args_is_help=True,
)

# ── Sub-apps ───────────────────────────────────────────────────────────────────

app.add_typer(daemon_app, name="daemon")
app.add_typer(collections_app, name="collections")

# ── Top-level commands ─────────────────────────────────────────────────────────

app.command("init")(cmd_init)
app.command("serve")(cmd_serve)
app.command("status")(cmd_status)
app.command("info")(cmd_info)
app.command("ingest")(cmd_ingest)
app.command("store")(cmd_store)
app.command("search")(cmd_search)
app.command("keywords")(cmd_keywords)
app.command("ask")(cmd_ask)
app.command("graph")(cmd_graph)
app.command("compact")(cmd_compact)
app.command("enrich")(cmd_enrich)


if __name__ == "__main__":
    app()

"""
StixDB CLI — command-line interface for the engine.
"""
from __future__ import annotations

import asyncio
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint

app = typer.Typer(
    name="stix",
    help="StixDB — Reasoning Agentic Context Database CLI",
    rich_markup_mode="rich",
)
console = Console()


import os

try:
    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv(usecwd=True))
except ImportError:
    pass

default_port = int(os.getenv("STIXDB_API_PORT", "4020"))

@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Host to bind"),
    port: int = typer.Option(default_port, help="Port to serve on"),
    reload: bool = typer.Option(False, help="Enable hot reload (dev mode)"),
    log_level: str = typer.Option("info", help="Log level"),
):
    """Start the StixDB API server."""
    import uvicorn
    console.print(Panel(
        f"[bold cyan]StixDB Agentic Context DB[/bold cyan]\n"
        f"Server starting on [bold]http://{host}:{port}[/bold]\n"
        f"Docs: [underline]http://{host}:{port}/docs[/underline]",
        title="StixDB Engine",
        border_style="cyan",
    ))
    uvicorn.run(
        "stixdb.api.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )


@app.command()
def demo():
    """Run the basic_usage demo."""
    import subprocess, sys
    import os

    demo_path = os.path.join(os.path.dirname(__file__), "..", "examples", "basic_usage.py")
    subprocess.run([sys.executable, demo_path])


@app.command()
def multi_demo():
    """Run the multi-agent demo."""
    import subprocess, sys, os
    demo_path = os.path.join(os.path.dirname(__file__), "..", "examples", "multi_agent_demo.py")
    subprocess.run([sys.executable, demo_path])


@app.command()
def info():
    """Display StixDB engine information."""
    from stixdb import __version__
    table = Table(title="StixDB Engine Info", border_style="cyan")
    table.add_column("Property", style="bold")
    table.add_column("Value")
    table.add_row("Version", __version__)
    table.add_row("Description", "Reasoning Agentic Context Database")
    table.add_row("Docs", "https://github.com/stixdb-engine")
    console.print(table)


if __name__ == "__main__":
    app()

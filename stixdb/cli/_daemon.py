"""
stixdb daemon — background server sub-commands.

  start    Start the daemon (background process)
  stop     Stop the daemon
  restart  Restart the daemon
  status   Show process + API health
  logs     View / follow daemon log output

The daemon reads the same ~/.stixdb/config.json as `stixdb serve`.
The difference is that the daemon runs detached from the terminal,
performing autonomous DB maintenance (consolidation, pruning, summarisation).

Configure first:  stixdb init
Then start:       stixdb daemon start
"""
from __future__ import annotations

import os
import sys
from typing import Optional

import typer
from rich.panel import Panel
from rich.table import Table
from rich import box

from stixdb.cli._helpers import (
    GLOBAL_DIR, GLOBAL_CONFIG, DAEMON_PID, DAEMON_LOG,
    console, load_global_config, daemon_running, require_global_config,
)

daemon_app = typer.Typer(
    help=(
        "[bold]Background daemon[/bold] — StixDB as a persistent background process.\n\n"
        "Reads [bold]~/.stixdb/config.json[/bold] (same as [cyan]stixdb serve[/cyan]).\n"
        "Runs detached, handling autonomous memory maintenance.\n\n"
        "  [cyan]stixdb init[/cyan]           Configure first\n"
        "  [cyan]stixdb daemon start[/cyan]   Start the background daemon\n"
        "  [cyan]stixdb daemon status[/cyan]  Check if it is running"
    ),
    rich_markup_mode="rich",
    no_args_is_help=True,
)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _detach_kwargs() -> dict:
    """Cross-platform subprocess kwargs to detach from the parent process."""
    if sys.platform == "win32":
        import subprocess as _sp
        return {
            "creationflags": _sp.CREATE_NEW_PROCESS_GROUP | _sp.DETACHED_PROCESS,
            "close_fds": True,
        }
    return {"start_new_session": True, "close_fds": True}


# ─────────────────────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────────────────────

@daemon_app.command("start")
def daemon_start(
    host: str = typer.Option("0.0.0.0", help="Host to bind."),
    port: int = typer.Option(0, help="Port (0 = read from config, default 4020)."),
    log_level: str = typer.Option("info", help="Uvicorn log level."),
    foreground: bool = typer.Option(
        False, "--fg", "--foreground",
        help="Run in the foreground instead of detaching (useful for debugging).",
    ),
):
    """
    [bold]Start the StixDB daemon[/bold] in the background.

    Reads [bold]~/.stixdb/config.json[/bold]. The daemon runs persistently
    and handles autonomous memory maintenance (consolidation, decay, pruning).

    Access the API at the configured port from any directory or any machine
    that can reach this host.

    [dim]--fg runs in the foreground — handy when debugging startup issues.[/dim]
    """
    require_global_config()

    running, pid = daemon_running()
    if running:
        console.print(Panel(
            f"[yellow]Daemon is already running[/yellow]  PID=[bold]{pid}[/bold]\n\n"
            "  [cyan]stixdb daemon status[/cyan]    Details\n"
            "  [cyan]stixdb daemon restart[/cyan]   Restart",
            border_style="yellow",
        ))
        raise typer.Exit(0)

    cf = load_global_config()
    if port == 0:
        port = (cf.server.port if cf else None) or 4020

    os.environ["STIXDB_PROJECT_DIR"] = str(GLOBAL_DIR.parent)
    os.environ["STIXDB_DAEMON_MODE"] = "1"
    dh = "localhost" if host == "0.0.0.0" else host

    if foreground:
        import uvicorn
        console.print(Panel(
            f"[bold cyan]StixDB Daemon[/bold cyan]  (foreground)\n\n"
            f"  Config : [dim]{GLOBAL_CONFIG}[/dim]\n"
            f"  URL    : [underline]http://{dh}:{port}[/underline]\n\n"
            "[dim]Ctrl+C to stop.[/dim]",
            title="[bold]stixdb daemon start --fg[/bold]",
            border_style="bold cyan",
            padding=(1, 2),
        ))
        uvicorn.run("stixdb.api.server:app", host=host, port=port, log_level=log_level)
        return

    # ── Background ─────────────────────────────────────────────────────────────
    GLOBAL_DIR.mkdir(parents=True, exist_ok=True)
    import subprocess
    # os.environ already has ~/.stixdb/.env loaded above; copy it all to subprocess
    env = os.environ.copy()
    env["STIXDB_PROJECT_DIR"] = str(GLOBAL_DIR.parent)
    env["STIXDB_DAEMON_MODE"] = "1"

    with open(DAEMON_LOG, "a") as log_fh:
        proc = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn", "stixdb.api.server:app",
                "--host", host, "--port", str(port), "--log-level", log_level,
            ],
            stdout=log_fh,
            stderr=log_fh,
            env=env,
            **_detach_kwargs(),
        )

    DAEMON_PID.write_text(str(proc.pid))
    console.print(Panel(
        f"[green]✓[/green] Daemon started  PID=[bold]{proc.pid}[/bold]\n\n"
        f"  URL    : [underline]http://{dh}:{port}[/underline]\n"
        f"  Config : [dim]{GLOBAL_CONFIG}[/dim]\n"
        f"  Log    : [dim]{DAEMON_LOG}[/dim]\n\n"
        "  [cyan]stixdb daemon status[/cyan]   Check status\n"
        "  [cyan]stixdb daemon logs[/cyan]     View logs\n"
        "  [cyan]stixdb daemon stop[/cyan]     Stop the daemon",
        title="[bold green]Daemon started[/bold green]",
        border_style="green",
        padding=(1, 2),
    ))


@daemon_app.command("stop")
def daemon_stop():
    """[bold]Stop the running daemon.[/bold]"""
    running, pid = daemon_running()
    if not running:
        console.print("[yellow]Daemon is not running.[/yellow]")
        DAEMON_PID.unlink(missing_ok=True)
        raise typer.Exit(0)
    try:
        if sys.platform == "win32":
            import subprocess as _sp
            result = _sp.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True, text=True,
            )
            if result.returncode != 0 and "not found" not in result.stderr.lower():
                console.print(f"[red]Failed to stop daemon PID {pid}:[/red] {result.stderr.strip()}")
                raise typer.Exit(1)
        else:
            import signal
            os.kill(pid, signal.SIGTERM)
        DAEMON_PID.unlink(missing_ok=True)
        console.print(f"[green]✓[/green] Daemon (PID [bold]{pid}[/bold]) stopped.")
    except typer.Exit:
        raise
    except Exception as exc:
        console.print(f"[red]Failed to stop daemon PID {pid}:[/red] {exc}")
        raise typer.Exit(1)


@daemon_app.command("restart")
def daemon_restart(
    host: str = typer.Option("0.0.0.0", help="Host to bind."),
    port: int = typer.Option(0, help="Port (0 = read from config)."),
):
    """[bold]Restart the daemon.[/bold]  Stops then starts."""
    daemon_stop()
    import time
    time.sleep(1)
    daemon_start(host=host, port=port, log_level="info", foreground=False)


@daemon_app.command("status")
def daemon_status():
    """
    [bold]Show daemon status.[/bold]

    Reports whether the process is alive and whether the API is reachable,
    and lists loaded collections.
    """
    running, pid = daemon_running()

    if not running:
        console.print(Panel(
            "[red]●[/red] Daemon is [bold]not running[/bold]\n\n"
            "Start it with [cyan]stixdb daemon start[/cyan]",
            title="StixDB Daemon",
            border_style="red",
        ))
        raise typer.Exit(0)

    cf = load_global_config()
    port = cf.server.port if cf else 4020
    api_key: Optional[str] = cf.server.api_key if cf else None

    url = f"http://localhost:{port}"
    api_ok, collections = False, []
    try:
        import httpx
        r = httpx.get(
            f"{url}/health",
            headers={"X-API-Key": api_key} if api_key else {},
            timeout=30,
        )
        if r.status_code == 200:
            api_ok = True
            collections = r.json().get("collections", [])
    except Exception:
        pass

    api_str = (
        f"[green]reachable[/green] at [underline]{url}[/underline]"
        if api_ok else
        "[yellow]process running, API not yet ready[/yellow]"
    )
    console.print(Panel(
        f"[green]●[/green] Running  PID=[bold]{pid}[/bold]\n\n"
        f"  API         : {api_str}\n"
        f"  Config      : [dim]{GLOBAL_CONFIG}[/dim]\n"
        f"  Log         : [dim]{DAEMON_LOG}[/dim]\n"
        f"  Collections : [bold]{len(collections)}[/bold]",
        title="StixDB Daemon",
        border_style="green" if api_ok else "yellow",
    ))

    if collections:
        t = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
        t.add_column("#", justify="right", style="dim")
        t.add_column("Collection")
        for i, c in enumerate(collections, 1):
            t.add_row(str(i), str(c))
        console.print(t)


@daemon_app.command("logs")
def daemon_logs(
    lines: int = typer.Option(50, "--lines", "-n", help="Number of recent lines to show."),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow output (like tail -f)."),
):
    """
    [bold]View daemon log output.[/bold]

    Shows the last N lines of the daemon log.
    Use [cyan]--follow[/cyan] to stream new output in real time (Ctrl+C to stop).
    """
    if not DAEMON_LOG.exists():
        console.print(f"[yellow]No log file at {DAEMON_LOG}[/yellow]")
        raise typer.Exit(0)

    import collections as _col
    content = DAEMON_LOG.read_text(encoding="utf-8", errors="replace")
    for line in _col.deque(content.splitlines(), maxlen=lines):
        console.print(line)

    if follow:
        import time
        console.print(f"\n[dim]Following {DAEMON_LOG} — Ctrl+C to stop…[/dim]")
        with open(DAEMON_LOG, encoding="utf-8", errors="replace") as fh:
            fh.seek(0, 2)
            try:
                while True:
                    chunk = fh.readline()
                    if chunk:
                        console.print(chunk, end="")
                    else:
                        time.sleep(0.25)
            except KeyboardInterrupt:
                pass

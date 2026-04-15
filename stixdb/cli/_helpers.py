"""
Shared path constants, HTTP helpers, config loaders, and daemon utilities.
Imported by all other cli sub-modules — keep this dependency-free of the
rest of the cli package to avoid circular imports.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import io
import sys

import typer
from rich.console import Console
from rich.panel import Panel

# On Windows the default stdout uses cp1252 which can't render Unicode glyphs
# like ● or ✓.  Wrapping with a UTF-8 TextIOWrapper bypasses the legacy
# Windows console renderer so all Rich markup works correctly.
def _utf8_console() -> Console:
    if hasattr(sys.stdout, "buffer"):
        return Console(file=io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8"))
    return Console()

console = _utf8_console()

# ── Universal paths ────────────────────────────────────────────────────────────
#   ~/.stixdb/  is the single source of truth for all StixDB state.
#   stixdb init     → ~/.stixdb/config.json
#   stixdb serve    → reads ~/.stixdb/config.json  (foreground)
#   stixdb daemon   → reads ~/.stixdb/config.json  (background)

GLOBAL_DIR    = Path.home() / ".stixdb"
GLOBAL_CONFIG = GLOBAL_DIR / "config.json"
DAEMON_PID    = GLOBAL_DIR / "daemon.pid"
DAEMON_LOG    = GLOBAL_DIR / "daemon.log"


# ── Config helpers ─────────────────────────────────────────────────────────────

def load_global_config():
    """Return the global ConfigFile, or None if missing / unreadable."""
    from stixdb.config import ConfigFile
    if GLOBAL_CONFIG.exists():
        try:
            return ConfigFile.load(GLOBAL_CONFIG)
        except Exception as exc:
            console.print(f"[yellow]Warning:[/yellow] Could not read {GLOBAL_CONFIG}: {exc}")
    return None


def require_global_config() -> None:
    """Exit early with a helpful message if ~/.stixdb/config.json is missing."""
    if not GLOBAL_CONFIG.exists():
        console.print(Panel(
            "[yellow]No config found at ~/.stixdb/config.json[/yellow]\n\n"
            "Run [cyan]stixdb init[/cyan] to configure StixDB.",
            border_style="yellow",
        ))
        raise typer.Exit(1)


def resolved_port(default: int = 4020) -> int:
    """Return the server port from config, falling back to env var or default."""
    cf = load_global_config()
    if cf:
        return cf.server.port
    return int(os.getenv("STIXDB_API_PORT", str(default)))


def resolved_api_key() -> Optional[str]:
    """Return the server API key read directly from config.json."""
    cf = load_global_config()
    return cf.server.api_key or None if cf else None


def default_collection() -> str:
    cf = load_global_config()
    return cf.default_collection if cf else "main"


# ── HTTP helpers ───────────────────────────────────────────────────────────────
# A single persistent Client is reused across all CLI calls within a process.
# On Windows, creating a new httpx connection per call adds ~2s TCP overhead;
# reusing the same client keeps subsequent calls at 3-30ms.

_http_client: Optional["httpx.Client"] = None  # type: ignore[name-defined]


def _client() -> "httpx.Client":  # type: ignore[name-defined]
    global _http_client
    if _http_client is None:
        import httpx
        _http_client = httpx.Client()
    return _http_client


def server_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def http_get(url: str, api_key: Optional[str] = None, timeout: int = 60) -> dict:
    import httpx
    headers = {"X-API-Key": api_key} if api_key else {}
    try:
        r = _client().get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        console.print(f"[red]✗[/red] Cannot reach server at [bold]{url}[/bold]")
        console.print("  Start one with [cyan]stixdb serve[/cyan] or [cyan]stixdb daemon start[/cyan].")
        raise typer.Exit(1)
    except httpx.ReadTimeout:
        console.print(f"[red]✗[/red] Server timed out after {timeout}s: [bold]{url}[/bold]")
        console.print("  The server is busy or the collection is loading. Try again in a moment.")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]HTTP {exc.response.status_code}:[/red] {exc.response.text}")
        raise typer.Exit(1)


def http_post(url: str, payload: dict, api_key: Optional[str] = None, timeout: int = 120) -> dict:
    import httpx
    headers = (
        {"X-API-Key": api_key, "Content-Type": "application/json"}
        if api_key
        else {"Content-Type": "application/json"}
    )
    try:
        r = _client().post(url, json=payload, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        console.print(f"[red]✗[/red] Cannot reach server at [bold]{url}[/bold]")
        console.print("  Start one with [cyan]stixdb serve[/cyan] or [cyan]stixdb daemon start[/cyan].")
        raise typer.Exit(1)
    except httpx.ReadTimeout:
        console.print(f"[red]✗[/red] Server timed out after {timeout}s: [bold]{url}[/bold]")
        console.print("  The server is busy. Try again in a moment.")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]HTTP {exc.response.status_code}:[/red] {exc.response.text}")
        raise typer.Exit(1)


def http_stream_post(url: str, payload: dict, api_key: Optional[str] = None, timeout: int = 300):
    """
    POST *url* and yield parsed JSON objects from a Server-Sent Events response.
    Each SSE line is expected to be:  ``data: <json>\\n\\n``
    The stream ends when a ``data: [DONE]`` sentinel is received.
    """
    import httpx
    import json as _json

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    try:
        with _client().stream("POST", url, json=payload, headers=headers, timeout=timeout) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                line = line.strip()
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    yield _json.loads(data)
                except _json.JSONDecodeError:
                    pass
    except httpx.ConnectError:
        console.print(f"[red]✗[/red] Cannot reach server at [bold]{url}[/bold]")
        console.print("  Start one with [cyan]stixdb serve[/cyan] or [cyan]stixdb daemon start[/cyan].")
        raise typer.Exit(1)
    except httpx.ReadTimeout:
        console.print(f"[red]✗[/red] Server timed out after {timeout}s: [bold]{url}[/bold]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]HTTP {exc.response.status_code}:[/red] {exc.response.text}")
        raise typer.Exit(1)


def http_delete(url: str, api_key: Optional[str] = None, timeout: int = 60) -> dict:
    import httpx
    headers = {"X-API-Key": api_key} if api_key else {}
    try:
        r = _client().delete(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        console.print(f"[red]✗[/red] Cannot reach server at [bold]{url}[/bold]")
        raise typer.Exit(1)
    except httpx.ReadTimeout:
        console.print(f"[red]✗[/red] Server timed out after {timeout}s: [bold]{url}[/bold]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]HTTP {exc.response.status_code}:[/red] {exc.response.text}")
        raise typer.Exit(1)


# ── Daemon helpers ─────────────────────────────────────────────────────────────

def daemon_running() -> tuple[bool, Optional[int]]:
    """Return (is_alive, pid). Uses psutil when available, falls back to os.kill."""
    if not DAEMON_PID.exists():
        return False, None
    try:
        pid = int(DAEMON_PID.read_text().strip())
        try:
            import psutil
            alive = psutil.pid_exists(pid)
        except ImportError:
            os.kill(pid, 0)   # raises if dead
            alive = True
        if alive:
            return True, pid
        return False, None
    except Exception:
        return False, None


def require_daemon() -> None:
    """Exit with a clear error if the daemon process is not running."""
    running, _ = daemon_running()
    if not running:
        console.print(Panel(
            "[red]Daemon is not running.[/red]\n\n"
            "Start it with  [cyan]stixdb daemon start[/cyan]\n"
            "Check status   [cyan]stixdb daemon status[/cyan]",
            border_style="red",
        ))
        raise typer.Exit(1)

"""
StixDB Interactive Setup Wizard
================================
Run via:  stixdb init

Walks through 4 steps and writes config.json.

API keys can be entered as:
  • An env var NAME  (e.g. NEBIUS_API_KEY)  — stored by reference, safe to commit
  • A raw key value  (e.g. v1.CmMK…)       — auto-saved to .env in config dir,
                                               config.json stores only the var name
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table
from rich import box

from stixdb.config import (
    AgentFileConfig,
    ConfigFile,
    EmbeddingFileConfig,
    IngestionFileConfig,
    LLMFileConfig,
    ObservabilityFileConfig,
    VLMFileConfig,
    KNOWN_EMBEDDING_DIMENSIONS,
    LLM_MODEL_SUGGESTIONS,
    EMBEDDING_MODEL_SUGGESTIONS,
    VLM_MODEL_SUGGESTIONS,
    NAMED_LLM_PRESETS,
    NAMED_EMBEDDING_PRESETS,
    ServerFileConfig,
    StorageFileConfig,
)

console = Console()

_LLM_PROVIDERS   = ["openai", "anthropic", "nebius", "openrouter", "ollama", "custom", "none"]
_EMBED_PROVIDERS = ["local", "openai", "nebius", "openrouter", "ollama", "custom"]
_VLM_PROVIDERS   = ["openai", "anthropic", "nebius", "openrouter", "ollama", "custom", "none"]

_PROVIDER_LABELS = {
    "openai":     "OpenAI (GPT-4o, o3-mini, …)",
    "anthropic":  "Anthropic (Claude Opus, Sonnet, …)",
    "nebius":     "Nebius AI Studio (OpenAI-compatible)",
    "openrouter": "OpenRouter (multi-provider gateway)",
    "ollama":     "Ollama (local models)",
    "custom":     "Custom OpenAI-compatible endpoint",
    "none":       "No LLM — heuristic search only",
    "local":      "Local (sentence-transformers, free, no API key)",
}

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _choose(prompt: str, choices: list[str], default: Optional[str] = None) -> str:
    """Prompt user to pick from a fixed list, re-prompting until valid."""
    choices_lower = [c.lower() for c in choices]
    hint = " / ".join(choices)
    while True:
        val = Prompt.ask(prompt, default=default or choices[0]).strip().lower()
        if val in choices_lower:
            return val
        console.print(f"  [red]Invalid choice.[/red] Pick one of: {hint}")


def _key_prompt(label: str) -> Optional[str]:
    """Prompt for an API key value. Returns None if left blank."""
    val = Prompt.ask(f"  {label}", default="").strip()
    if not val:
        console.print(f"  [dim]Skipped — set later if needed.[/dim]\n")
        return None
    console.print(f"  [green]✓[/green] Key set.\n")
    return val


def _model_prompt(provider: str, suggestions: dict[str, list[str]], default_map: dict[str, str]) -> str:
    """Show model suggestions and prompt for a model name."""
    opts = suggestions.get(provider, [])
    if opts:
        console.print(f"  Suggested models for [cyan]{provider}[/cyan]:")
        for i, m in enumerate(opts, 1):
            console.print(f"    [{i}] {m}")
        console.print()
    default_model = default_map.get(provider, opts[0] if opts else "")
    val = Prompt.ask("  Model name", default=default_model).strip()
    if val.isdigit() and opts:
        idx = int(val) - 1
        if 0 <= idx < len(opts):
            val = opts[idx]
    return val


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — LLM Provider
# ─────────────────────────────────────────────────────────────────────────────

def _step_llm() -> LLMFileConfig:
    console.print(Panel(
        "[bold]Step 1 / 4 — LLM Provider[/bold]\n"
        "Which model will reason over your memory graph?",
        border_style="cyan", padding=(0, 2),
    ))

    console.print("  Available providers:\n")
    for p in _LLM_PROVIDERS:
        console.print(f"    [cyan]{p:<12}[/cyan] {_PROVIDER_LABELS.get(p, '')}")
    console.print()

    provider = _choose("  Provider", _LLM_PROVIDERS, default="nebius")

    if provider == "none":
        return LLMFileConfig(provider="none", model="none")

    # Base URL
    base_url: Optional[str] = None
    if provider in NAMED_LLM_PRESETS:
        preset_url = NAMED_LLM_PRESETS[provider]["base_url"]
        console.print(f"  [dim]Base URL for {provider}: {preset_url}[/dim]")
        base_url = preset_url
    elif provider == "ollama":
        base_url = Prompt.ask("  Ollama base URL", default="http://localhost:11434").strip()
    elif provider == "custom":
        base_url = Prompt.ask("  Base URL (required)").strip()
        if not base_url:
            console.print("  [red]Base URL is required for custom provider.[/red]")
            return _step_llm()

    # API key
    api_key: Optional[str] = None
    if provider not in ("none", "ollama"):
        api_key = _key_prompt("API key")

    # Model
    _DEFAULT_MODELS = {
        "openai": "gpt-4o", "anthropic": "claude-sonnet-4-6",
        "nebius": "openai/gpt-oss-120b", "openrouter": "openai/gpt-4o",
        "ollama": "llama3.2", "custom": "",
    }
    model = _model_prompt(provider, LLM_MODEL_SUGGESTIONS, _DEFAULT_MODELS)

    # Reasoning / inference parameters
    console.print("\n  [bold]Reasoning parameters[/bold]  [dim](press Enter to accept defaults)[/dim]\n")
    temperature         = float(Prompt.ask("  Temperature",           default="0.2").strip())
    max_tokens          = IntPrompt.ask("  Max tokens",               default=2048)
    max_context_nodes   = IntPrompt.ask("  Max context nodes",        default=20)
    graph_traversal_depth = IntPrompt.ask("  Graph traversal depth",  default=3)
    timeout             = float(Prompt.ask("  API timeout (seconds)", default="60.0").strip())

    return LLMFileConfig(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url if provider in ("ollama", "custom") else None,
        temperature=temperature,
        max_tokens=max_tokens,
        max_context_nodes=max_context_nodes,
        graph_traversal_depth=graph_traversal_depth,
        timeout=timeout,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Embedding Model
# ─────────────────────────────────────────────────────────────────────────────

def _step_embedding(llm_cfg: LLMFileConfig) -> EmbeddingFileConfig:
    console.print(Panel(
        "[bold]Step 2 / 4 — Embedding Model[/bold]\n"
        "Which model converts text to vectors for semantic search?",
        border_style="cyan", padding=(0, 2),
    ))

    console.print("  Available providers:\n")
    for p in _EMBED_PROVIDERS:
        console.print(f"    [cyan]{p:<12}[/cyan] {_PROVIDER_LABELS.get(p, '')}")
    console.print()

    default_embed_provider = llm_cfg.provider if llm_cfg.provider in _EMBED_PROVIDERS else "local"
    provider = _choose("  Provider", _EMBED_PROVIDERS, default=default_embed_provider)

    # Base URL
    base_url: Optional[str] = None
    if provider in NAMED_EMBEDDING_PRESETS:
        base_url = NAMED_EMBEDDING_PRESETS[provider]["base_url"]
        console.print(f"  [dim]Base URL for {provider}: {base_url}[/dim]")
    elif provider == "ollama":
        base_url = Prompt.ask("  Ollama base URL", default="http://localhost:11434").strip()
    elif provider == "custom":
        base_url = Prompt.ask("  Base URL (required)").strip()

    # API key — offer to reuse LLM key if same provider
    api_key: Optional[str] = None
    if provider not in ("local", "ollama"):
        if provider == llm_cfg.provider and llm_cfg.api_key:
            reuse = Confirm.ask(
                "  Reuse same API key as LLM?",
                default=True,
            )
            api_key = llm_cfg.api_key if reuse else _key_prompt("API key")
        else:
            api_key = _key_prompt("API key")

    # Model
    _DEFAULT_EMBED_MODELS = {
        "local": "all-MiniLM-L6-v2", "openai": "text-embedding-3-small",
        "nebius": "Qwen/Qwen3-Embedding-8B", "openrouter": "text-embedding-3-small",
        "ollama": "nomic-embed-text", "custom": "",
    }
    model = _model_prompt(provider, EMBEDDING_MODEL_SUGGESTIONS, _DEFAULT_EMBED_MODELS)

    # Dimensions — auto-detect or prompt
    auto_dims = KNOWN_EMBEDDING_DIMENSIONS.get(model)
    if auto_dims:
        dims = IntPrompt.ask("  Embedding dimensions [auto-detected]", default=auto_dims)
    else:
        dims = IntPrompt.ask("  Embedding dimensions", default=384)

    return EmbeddingFileConfig(
        provider=provider,
        model=model,
        dimensions=dims,
        api_key=api_key,
        base_url=base_url if provider in ("ollama", "custom") else None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Step 2b — VLM (optional)
# ─────────────────────────────────────────────────────────────────────────────

def _step_vlm(llm_cfg: LLMFileConfig) -> Optional[VLMFileConfig]:
    console.print(Panel(
        "[bold]Step 2b / 5 — Vision Language Model (VLM) [dim](optional)[/dim][/bold]\n"
        "A VLM describes image files during ingestion so they become searchable.\n"
        "Skip this step if you don't plan to ingest images.",
        border_style="cyan", padding=(0, 2),
    ))

    if not Confirm.ask("  Configure a VLM for image ingestion?", default=False):
        console.print("  [dim]Skipping — images will be ignored during ingest.[/dim]")
        return None

    console.print("\n  Available providers:\n")
    for p in _VLM_PROVIDERS:
        console.print(f"    [cyan]{p:<12}[/cyan] {_PROVIDER_LABELS.get(p, '')}")
    console.print()

    default_vlm_provider = llm_cfg.provider if llm_cfg.provider in _VLM_PROVIDERS else "openai"
    provider = _choose("  Provider", _VLM_PROVIDERS, default=default_vlm_provider)

    if provider == "none":
        return None

    base_url: Optional[str] = None
    if provider in NAMED_LLM_PRESETS:
        base_url = NAMED_LLM_PRESETS[provider]["base_url"]
        console.print(f"  [dim]Base URL for {provider}: {base_url}[/dim]")
    elif provider == "ollama":
        base_url = Prompt.ask("  Ollama base URL", default="http://localhost:11434").strip()
    elif provider == "custom":
        base_url = Prompt.ask("  Base URL (required)").strip()
        if not base_url:
            console.print("  [red]Base URL is required for custom provider.[/red]")
            return _step_vlm(llm_cfg)

    api_key: Optional[str] = None
    if provider not in ("none", "ollama"):
        if provider == llm_cfg.provider and llm_cfg.api_key:
            reuse = Confirm.ask("  Reuse same API key as LLM?", default=True)
            api_key = llm_cfg.api_key if reuse else _key_prompt("API key")
        else:
            api_key = _key_prompt("API key")

    _DEFAULT_VLM_MODELS = {
        "openai":     "gpt-4o-mini",
        "anthropic":  "claude-sonnet-4-6",
        "nebius":     "Qwen/Qwen2-VL-72B-Instruct",
        "openrouter": "openai/gpt-4o",
        "ollama":     "llava:latest",
        "custom":     "",
    }
    model = _model_prompt(provider, VLM_MODEL_SUGGESTIONS, _DEFAULT_VLM_MODELS)

    return VLMFileConfig(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url if provider in ("ollama", "custom") else None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — Storage
# ─────────────────────────────────────────────────────────────────────────────

def _step_storage() -> StorageFileConfig:
    console.print(Panel(
        "[bold]Step 3 / 4 — Storage[/bold]\n"
        "StixDB uses [bold cyan]KuzuDB[/bold cyan] — embedded graph database, "
        "no Docker required, persists to disk.",
        border_style="cyan", padding=(0, 2),
    ))

    path = Prompt.ask("  Data directory", default="~/.stixdb/data").strip()
    return StorageFileConfig(mode="kuzu", path=path)


# ─────────────────────────────────────────────────────────────────────────────
# Step 4 — Agent & Memory
# ─────────────────────────────────────────────────────────────────────────────

def _step_agent() -> AgentFileConfig:
    _DEFAULTS = AgentFileConfig(cycle_interval=300.0)

    console.print(Panel(
        "[bold]Step 4 / 5 — Agent & Memory[/bold]\n"
        "The autonomous memory-maintenance agent runs in the background.\n"
        "Sensible defaults are pre-configured — you can tune them now or skip.",
        border_style="cyan", padding=(0, 2),
    ))

    console.print()
    cycle_interval = float(Prompt.ask("  Cycle interval (seconds)", default="300.0").strip())

    if not Confirm.ask("  Configure advanced agent settings?", default=False):
        console.print("  [dim]Using defaults for all advanced agent parameters.[/dim]\n")
        return AgentFileConfig(cycle_interval=cycle_interval)

    # ── Advanced ──────────────────────────────────────────────────────────────
    console.print()
    consolidation_threshold = float(Prompt.ask(
        "  Consolidation similarity threshold  [dim](merge nodes above this cosine score)[/dim]",
        default="0.88").strip())
    decay_half_life_hours   = float(Prompt.ask(
        "  Decay half-life (hours)  [dim](unaccessed node importance halves after this)[/dim]",
        default="48.0").strip())
    prune_threshold         = float(Prompt.ask(
        "  Prune threshold  [dim](nodes below this importance score are removed)[/dim]",
        default="0.05").strip())
    working_memory_max      = IntPrompt.ask(
        "  Working memory max nodes  [dim](hot node cap)[/dim]", default=256)
    max_consolidation_batch = IntPrompt.ask(
        "  Max consolidation batch  [dim](nodes processed per cycle)[/dim]", default=64)
    auto_summarize          = Confirm.ask("  Auto-summarise large clusters?", default=True)
    lineage_safe_mode       = Confirm.ask(
        "  Lineage safe mode?  [dim](protect source nodes after summarisation)[/dim]", default=True)

    return AgentFileConfig(
        cycle_interval=cycle_interval,
        consolidation_threshold=consolidation_threshold,
        decay_half_life_hours=decay_half_life_hours,
        prune_threshold=prune_threshold,
        working_memory_max=working_memory_max,
        max_consolidation_batch=max_consolidation_batch,
        auto_summarize=auto_summarize,
        lineage_safe_mode=lineage_safe_mode,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Step 5 — Advanced
# ─────────────────────────────────────────────────────────────────────────────

def _step_advanced() -> tuple[IngestionFileConfig, ServerFileConfig, ObservabilityFileConfig, str]:
    console.print(Panel(
        "[bold]Step 5 / 5 — Advanced[/bold]\n"
        "Press [bold]Enter[/bold] to accept all defaults.",
        border_style="cyan", padding=(0, 2),
    ))

    _STRATEGIES = ["fixed", "paragraph", "sentence", "semantic", "page"]
    console.print("\n  [bold]Chunking strategy[/bold]")
    console.print("    [cyan]fixed[/cyan]      Fixed-size character windows [bold](default, fastest)[/bold]")
    console.print("    [cyan]paragraph[/cyan]  Split on double-newlines — preserves paragraph boundaries")
    console.print("    [cyan]sentence[/cyan]   Split on sentence boundaries (requires nltk)")
    console.print("    [cyan]semantic[/cyan]   Semantic chunking via embedding model (slowest, best quality)")
    console.print("    [cyan]page[/cyan]       One chunk per PDF page (PDFs only)\n")
    strategy      = _choose("  Strategy",            _STRATEGIES, default="fixed")
    chunk_size    = IntPrompt.ask("  Chunk size",    default=1000)
    chunk_overlap = IntPrompt.ask("  Chunk overlap", default=200)
    port          = IntPrompt.ask("  Server port",   default=4020)
    default_coll  = Prompt.ask("  Default collection", default="main").strip()
    server_api_key = Prompt.ask(
        "  Server API key [dim](leave blank = no auth)[/dim]",
        default="",
    ).strip() or None

    console.print("\n  [bold]Observability[/bold]")
    enable_traces  = Confirm.ask("  Enable traces?",  default=True)
    enable_metrics = Confirm.ask("  Enable metrics?", default=True)
    metrics_port   = IntPrompt.ask("  Metrics port",  default=9090)
    log_level      = _choose("  Log level", ["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO").upper()

    ingestion     = IngestionFileConfig(chunk_size=chunk_size, chunk_overlap=chunk_overlap, strategy=strategy)
    server        = ServerFileConfig(port=port, api_key=server_api_key)
    observability = ObservabilityFileConfig(
        enable_traces=enable_traces,
        enable_metrics=enable_metrics,
        metrics_port=metrics_port,
        log_level=log_level,
    )
    return ingestion, server, observability, default_coll


# ─────────────────────────────────────────────────────────────────────────────
# Preview
# ─────────────────────────────────────────────────────────────────────────────

def _preview(cf: ConfigFile) -> None:
    console.print()
    t = Table(title="Config Preview", box=box.SIMPLE_HEAVY, show_header=True, header_style="bold")
    t.add_column("Section",  style="cyan", min_width=12)
    t.add_column("Field",    style="bold", min_width=16)
    t.add_column("Value")

    def _key_display(key: Optional[str]) -> str:
        if not key:
            return "[dim]—[/dim]"
        masked = key[:6] + "…" + key[-4:] if len(key) > 12 else "***"
        return f"[green]✓[/green] {masked}"

    t.add_row("llm",       "provider",              cf.llm.provider)
    t.add_row("",          "model",                 cf.llm.model)
    t.add_row("",          "api_key",               _key_display(cf.llm.api_key))
    if cf.llm.base_url:
        t.add_row("",      "base_url",              cf.llm.base_url)
    t.add_row("",          "temperature",           str(cf.llm.temperature))
    t.add_row("",          "max_tokens",            str(cf.llm.max_tokens))
    t.add_row("",          "max_context_nodes",     str(cf.llm.max_context_nodes))
    t.add_row("",          "graph_traversal_depth", str(cf.llm.graph_traversal_depth))
    t.add_row("",          "timeout",               f"{cf.llm.timeout}s")
    t.add_row("embedding", "provider",              cf.embedding.provider)
    t.add_row("",          "model",                 cf.embedding.model)
    t.add_row("",          "dimensions",            str(cf.embedding.dimensions))
    t.add_row("",          "api_key",               _key_display(cf.embedding.api_key))
    t.add_row("storage",   "mode",                  cf.storage.mode)
    t.add_row("",          "path",                  cf.storage.path)
    t.add_row("ingestion", "chunk_size",            str(cf.ingestion.chunk_size))
    t.add_row("",          "chunk_overlap",         str(cf.ingestion.chunk_overlap))
    t.add_row("",          "strategy",              cf.ingestion.strategy)
    t.add_row("agent",     "cycle_interval",        f"{cf.agent.cycle_interval}s")
    t.add_row("",          "consolidation_threshold", str(cf.agent.consolidation_threshold))
    t.add_row("",          "decay_half_life",       f"{cf.agent.decay_half_life_hours}h")
    t.add_row("",          "prune_threshold",       str(cf.agent.prune_threshold))
    t.add_row("",          "working_memory_max",    str(cf.agent.working_memory_max))
    t.add_row("",          "max_consolidation_batch", str(cf.agent.max_consolidation_batch))
    t.add_row("",          "auto_summarize",        str(cf.agent.auto_summarize))
    t.add_row("",          "lineage_safe_mode",     str(cf.agent.lineage_safe_mode))
    t.add_row("observability", "enable_traces",     str(cf.observability.enable_traces))
    t.add_row("",          "enable_metrics",        str(cf.observability.enable_metrics))
    t.add_row("",          "metrics_port",          str(cf.observability.metrics_port))
    t.add_row("",          "log_level",             cf.observability.log_level)
    t.add_row("server",    "port",                  str(cf.server.port))
    t.add_row("",          "api_key",               _key_display(cf.server.api_key))
    t.add_row("general",   "default_collection",    cf.default_collection)

    console.print(t)


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_wizard(config_dir: Path) -> ConfigFile:
    """
    Run the interactive setup wizard.
    config_dir — directory where config.json (and optionally .env) will be written.
    Returns a ready-to-save ConfigFile.  Raises KeyboardInterrupt on cancel.
    """
    config_dir.mkdir(parents=True, exist_ok=True)

    console.print(Panel(
        "[bold white]Welcome to StixDB Setup[/bold white]\n\n"
        "This wizard configures StixDB and saves [bold]config.json[/bold].\n"
        "API keys are stored directly in config.json — keep this file private.\n\n"
        "Press [bold]Ctrl+C[/bold] at any time to cancel.",
        border_style="bold cyan",
        padding=(1, 4),
    ))
    console.print()

    try:
        llm_cfg                                          = _step_llm()
        console.print()
        emb_cfg                                          = _step_embedding(llm_cfg)
        console.print()
        vlm_cfg                                          = _step_vlm(llm_cfg)
        console.print()
        storage_cfg                                      = _step_storage()
        console.print()
        agent_cfg                                        = _step_agent()
        console.print()
        ingestion_cfg, server_cfg, obs_cfg, default_coll = _step_advanced()
    except KeyboardInterrupt:
        console.print("\n[yellow]Setup cancelled.[/yellow]")
        raise

    cf = ConfigFile(
        llm=llm_cfg,
        embedding=emb_cfg,
        vlm=vlm_cfg,
        storage=storage_cfg,
        ingestion=ingestion_cfg,
        agent=agent_cfg,
        observability=obs_cfg,
        server=server_cfg,
        default_collection=default_coll,
    )

    _preview(cf)
    console.print()

    if not Confirm.ask("Save this config?", default=True):
        raise KeyboardInterrupt

    return cf

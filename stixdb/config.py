"""
StixDB Engine Configuration.
Single source of truth for all runtime settings.
"""
from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"
    CUSTOM = "custom"
    NONE = "none"  # Disable LLM; use heuristics only


class EmbeddingProvider(str, Enum):
    SENTENCE_TRANSFORMERS = "sentence_transformers"
    OPENAI = "openai"
    OLLAMA = "ollama"
    CUSTOM = "custom"


class StorageMode(str, Enum):
    MEMORY = "memory"   # NetworkX in-process — no Docker, no persistence (dev / testing)
    KUZU   = "kuzu"     # KuzuDB embedded — no Docker, persistent on disk (local dev)
    NEO4J  = "neo4j"    # Neo4j — requires Docker (production)


class VectorBackend(str, Enum):
    CHROMA = "chroma"
    QDRANT = "qdrant"
    MEMORY = "memory"          # Pure in-memory numpy cosine search



class AgentConfig(BaseModel):
    """Configuration for the autonomous Memory Agent."""
    cycle_interval_seconds: float = Field(30.0, ge=1.0, description="How often the agent runs its perceive-plan-act loop.")
    consolidation_similarity_threshold: float = Field(0.88, ge=0.5, le=1.0, description="Cosine similarity above which two nodes are merged.")
    decay_half_life_hours: float = Field(48.0, ge=1.0, description="Hours for an unaccessed node's importance to halve.")
    prune_importance_threshold: float = Field(0.05, ge=0.0, le=1.0, description="Nodes below this importance score will be pruned.")
    working_memory_max_nodes: int = Field(256, ge=16, description="Max nodes that live in the 'hot' working memory cluster.")
    max_consolidation_batch: int = Field(64, description="Max nodes the consolidator processes in a single cycle.")
    enable_auto_summarize: bool = True
    lineage_safe_mode: bool = Field(
        True,
        description="Protect source nodes that contribute to summaries from later pruning.",
    )

    # ── Synthesis zone ────────────────────────────────────────────────────
    synthesis_similarity_lower: float = Field(
        0.55, ge=0.2, le=0.95,
        description=(
            "Lower bound of the synthesis zone. Node pairs with similarity between "
            "this value and consolidation_similarity_threshold get a synthesis "
            "SUMMARY node created WITHOUT archiving the originals. This is the "
            "primary mechanism for building higher-level abstractions."
        ),
    )
    max_synthesis_batch: int = Field(
        40, ge=4,
        description="Max pairs synthesized per cycle (LLM calls are expensive).",
    )

    # ── Librarian Agent: RelationWeaver ───────────────────────────────────
    enable_relation_weaving: bool = Field(
        True,
        description="Enable autonomous relation discovery between related-but-distinct nodes.",
    )
    relation_similarity_lower: float = Field(
        0.40, ge=0.1, le=0.9,
        description="Lower bound of the relation band. Pairs below this are unrelated.",
    )
    weaver_batch_size: int = Field(
        60, ge=8,
        description="Nodes sampled per weaver pass (total across tiers).",
    )
    weaver_batch_limit: int = Field(
        20, ge=1,
        description="Max pairs classified (and potentially woven) per weaver pass.",
    )

    # ── Librarian Agent: PredictivePrefetcher ─────────────────────────────
    enable_predictive_prefetch: bool = Field(
        True,
        description="Enable proactive working-memory pre-warming from past query patterns.",
    )
    prefetch_history_size: int = Field(
        50, ge=5,
        description="Rolling window of past queries kept for pattern matching.",
    )
    prefetch_top_k_records: int = Field(
        5, ge=1,
        description="Top-K most similar past queries used for prefetch decisions.",
    )
    prefetch_max_promote: int = Field(
        30, ge=1,
        description="Max nodes promoted to working memory per pattern-prefetch pass.",
    )
    enable_neighbor_fanout: bool = Field(
        True,
        description="Fan out from hot nodes: pre-promote their graph neighbors.",
    )
    fanout_hot_node_limit: int = Field(
        10, ge=1,
        description="Max hot nodes fanned-out from per cycle.",
    )
    prefetch_max_fanout: int = Field(
        20, ge=1,
        description="Max total nodes promoted via neighbor fan-out per cycle.",
    )


class ReasonerConfig(BaseModel):
    """Configuration for the LLM-backed Reasoner."""
    provider: LLMProvider = LLMProvider.OPENAI
    model: str = "gpt-4o"
    temperature: float = 0.2
    max_tokens: int = 4096
    max_context_nodes: int = 20    # Max graph nodes passed to the LLM
    graph_traversal_depth: int = 3  # BFS depth for subgraph expansion
    timeout_seconds: float = 60.0
    # Provider-specific keys (prefer env vars)
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    ollama_base_url: str = "http://localhost:11434"
    custom_base_url: Optional[str] = None
    custom_api_key: Optional[str] = None


class StorageConfig(BaseModel):
    """Storage configuration.

    Three modes:
      MEMORY — in-process NetworkX + NumPy, no Docker required, data lost on exit.
      KUZU   — KuzuDB embedded graph, no Docker, fully persistent on disk (recommended for local dev).
      NEO4J  — persistent graph via Neo4j + ChromaDB/Qdrant vector store, requires Docker (production).
    """
    mode: StorageMode = StorageMode.MEMORY
    data_dir: str = "./stixdb_data"
    vector_backend: VectorBackend = VectorBackend.QDRANT
    # KuzuDB settings (local dev, no Docker needed)
    kuzu_path: str = "./stixdb_data/kuzu"
    kuzu_buffer_pool_mb: int = 4096
    # Qdrant settings (empty host = embedded local path under data_dir/qdrant)
    qdrant_host: str = ""
    qdrant_port: int = 6333
    # Chroma settings (docker: chroma service)
    chroma_host: Optional[str] = None
    # Neo4j settings (docker: neo4j service)
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"
    # SQL metadata (docker: postgres service)
    sql_url: str = "postgresql://stixdb:stixdb_pass@localhost:5432/stixdb"
    # Max nodes before archival
    max_active_nodes: int = 1_000_000


class EmbeddingConfig(BaseModel):
    """Configuration for embedding models."""
    provider: EmbeddingProvider = EmbeddingProvider.SENTENCE_TRANSFORMERS
    model: str = "all-MiniLM-L6-v2"
    dimensions: int = 384
    openai_api_key: Optional[str] = None
    ollama_base_url: str = "http://localhost:11434"
    custom_base_url: Optional[str] = None
    custom_api_key: Optional[str] = None


class ApiServerConfig(BaseModel):
    """Configuration for the StixDB FastAPI Server."""
    port: int = 4020
    api_key: Optional[str] = None


class BackupConfig(BaseModel):
    """Configuration for optional ingestion-time file backup."""
    enabled: bool = False
    endpoint: str = "localhost:9000"
    access_key: str = "minioadmin"
    secret_key: str = "minioadmin"
    bucket: str = "stixdb-ingestion"
    secure: bool = False
    prefix: str = "uploads"


class IngestionConfig(BaseModel):
    """Configuration for document ingestion."""
    default_chunk_size: int = 1000
    default_chunk_overlap: int = 200


# ─────────────────────────────────────────────────────────────────────────────
# ConfigFile — file-based configuration (.stixdb/config.json)
# Safe to commit to git: stores env var NAME references, never raw secrets.
# ─────────────────────────────────────────────────────────────────────────────

# Named provider presets (friendly names → internal enum + base_url)
NAMED_LLM_PRESETS: dict[str, dict] = {
    "nebius":     {"base_url": "https://api.studio.nebius.ai/v1/"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1"},
}
NAMED_EMBEDDING_PRESETS: dict[str, dict] = {
    "nebius":     {"base_url": "https://api.studio.nebius.ai/v1/"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1"},
}

# Model suggestions shown to users in the wizard
LLM_MODEL_SUGGESTIONS: dict[str, list[str]] = {
    "openai":      ["gpt-4o", "gpt-4o-mini", "o3-mini"],
    "anthropic":   ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"],
    "nebius":      ["openai/gpt-oss-120b", "meta-llama/Meta-Llama-3.1-70B-Instruct-fast"],
    "openrouter":  ["openai/gpt-4o", "anthropic/claude-3.5-sonnet", "google/gemini-pro"],
    "ollama":      ["llama3.2", "mistral", "qwen2.5"],
    "custom":      [],
    "none":        [],
}
EMBEDDING_MODEL_SUGGESTIONS: dict[str, list[str]] = {
    "local":       ["all-MiniLM-L6-v2", "all-mpnet-base-v2", "BAAI/bge-small-en-v1.5"],
    "openai":      ["text-embedding-3-small", "text-embedding-3-large"],
    "nebius":      ["Qwen/Qwen3-Embedding-8B", "BAAI/bge-m3"],
    "openrouter":  ["text-embedding-3-small"],
    "ollama":      ["nomic-embed-text", "mxbai-embed-large"],
    "custom":      [],
}
KNOWN_EMBEDDING_DIMENSIONS: dict[str, int] = {
    "all-MiniLM-L6-v2":         384,
    "all-mpnet-base-v2":         768,
    "BAAI/bge-small-en-v1.5":   384,
    "BAAI/bge-m3":               1024,
    "text-embedding-3-small":    1536,
    "text-embedding-3-large":    3072,
    "Qwen/Qwen3-Embedding-8B":   4096,
    "nomic-embed-text":          768,
    "mxbai-embed-large":         1024,
}


class LLMFileConfig(BaseModel):
    """LLM provider + reasoning parameters stored in config.json."""
    provider: str                       # "openai"|"anthropic"|"nebius"|"openrouter"|"ollama"|"custom"|"none"
    model: str
    api_key: Optional[str] = None      # raw key value — stored directly in config.json
    base_url: Optional[str] = None     # auto-set for nebius/openrouter; required for custom
    # Reasoning / inference parameters
    temperature: float = 0.2
    max_tokens: int = 4096
    max_context_nodes: int = 20        # graph nodes passed as context to the LLM
    graph_traversal_depth: int = 3     # BFS depth for subgraph expansion
    timeout: float = 60.0              # API call timeout in seconds


class EmbeddingFileConfig(BaseModel):
    """Embedding provider config stored in config.json."""
    provider: str                       # "local"|"openai"|"nebius"|"openrouter"|"ollama"|"custom"
    model: str
    dimensions: int = 384
    api_key: Optional[str] = None      # raw key value
    base_url: Optional[str] = None


class StorageFileConfig(BaseModel):
    """Storage config stored in config.json."""
    mode: str = "kuzu"                  # "kuzu"|"memory"|"neo4j"
    path: str = "./stixdb_data"
    kuzu_buffer_pool_mb: int = 4096
    neo4j_uri: Optional[str] = None
    neo4j_user_env: Optional[str] = None
    neo4j_password_env: Optional[str] = None


class IngestionFileConfig(BaseModel):
    """Ingestion / chunking config stored in config.json."""
    chunk_size: int = 1000
    chunk_overlap: int = 200
    strategy: str = "fixed"
    # "fixed"     — fixed-size character windows (fastest)
    # "paragraph" — split on double-newlines
    # "sentence"  — sentence boundaries (requires nltk)
    # "semantic"  — embedding-based chunking (slowest, best quality)
    # "page"      — one chunk per PDF page


class AgentFileConfig(BaseModel):
    """Autonomous memory-agent parameters stored in config.json."""
    cycle_interval: float = 300.0          # seconds between perceive/plan/act loops
    consolidation_threshold: float = 0.88  # cosine similarity above which nodes are merged
    decay_half_life_hours: float = 48.0    # hours for importance to halve when unaccessed
    prune_threshold: float = 0.05          # nodes below this importance are pruned
    working_memory_max: int = 256          # max hot nodes in working memory
    max_consolidation_batch: int = 64      # nodes processed per consolidation cycle
    auto_summarize: bool = True            # auto-summarise large node clusters
    lineage_safe_mode: bool = True         # protect source nodes from post-summary pruning
    # Synthesis zone
    synthesis_similarity_lower: float = 0.55
    max_synthesis_batch: int = 40
    # Librarian Agent — RelationWeaver
    enable_relation_weaving: bool = True
    relation_similarity_lower: float = 0.40
    weaver_batch_size: int = 60
    weaver_batch_limit: int = 20
    # Librarian Agent — PredictivePrefetcher
    enable_predictive_prefetch: bool = True
    prefetch_history_size: int = 50
    prefetch_max_promote: int = 30
    enable_neighbor_fanout: bool = True
    prefetch_max_fanout: int = 20


class ObservabilityFileConfig(BaseModel):
    """Tracing, metrics, and logging config stored in config.json."""
    enable_traces: bool = True
    enable_metrics: bool = True
    metrics_port: int = 9090
    log_level: str = "INFO"               # DEBUG | INFO | WARNING | ERROR


class ServerFileConfig(BaseModel):
    """HTTP server config stored in config.json."""
    port: int = 4020
    api_key: Optional[str] = None         # raw server auth key; None = no auth


class ConfigFile(BaseModel):
    """
    Complete StixDB configuration stored in config.json.

    API keys are stored as plain values — keep this file private.
    """
    llm: LLMFileConfig
    embedding: EmbeddingFileConfig
    storage: StorageFileConfig = Field(default_factory=StorageFileConfig)
    ingestion: IngestionFileConfig = Field(default_factory=IngestionFileConfig)
    agent: AgentFileConfig = Field(default_factory=AgentFileConfig)
    observability: ObservabilityFileConfig = Field(default_factory=ObservabilityFileConfig)
    server: ServerFileConfig = Field(default_factory=ServerFileConfig)
    default_collection: str = "main"

    def save(self, path: "Path") -> None:
        """Write config to disk as pretty-printed JSON."""
        from pathlib import Path as _Path
        p = _Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")

    @classmethod
    def load(cls, path: "Path") -> "ConfigFile":
        """Load and validate config from a JSON file."""
        from pathlib import Path as _Path
        return cls.model_validate_json(_Path(path).read_text(encoding="utf-8"))


class StixDBConfig(BaseModel):
    """
    Master configuration for a StixDBEngine instance.
    
    Example:
        config = StixDBConfig(
            storage=StorageConfig(mode=StorageMode.NEO4J),
            reasoner=ReasonerConfig(provider=LLMProvider.ANTHROPIC, model="claude-opus-4-6"),
        )
    """
    agent: AgentConfig = Field(default_factory=AgentConfig)
    reasoner: ReasonerConfig = Field(default_factory=ReasonerConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    ingestion: IngestionConfig = Field(default_factory=IngestionConfig)
    api: ApiServerConfig = Field(default_factory=ApiServerConfig)
    backup: BackupConfig = Field(default_factory=BackupConfig)

    # Observability
    verbose: bool = True  # Set to False to suppress maintenance and background agent logs
    enable_traces: bool = True
    enable_metrics: bool = True
    metrics_port: int = 9090
    log_level: str = "INFO"

    @classmethod
    def from_file(cls, path: "Path") -> "StixDBConfig":
        """Load config from a .stixdb/config.json file, resolving env var references at runtime."""
        from pathlib import Path as _Path
        cf = ConfigFile.load(_Path(path))
        return cls._from_config_file(cf)

    @classmethod
    def load(cls, project_dir: "Optional[Path]" = None) -> "StixDBConfig":
        """
        Smart loader: tries .stixdb/config.json → env vars → defaults.

        Resolution order:
          1. ``project_dir`` argument (if given)
          2. ``STIXDB_PROJECT_DIR`` environment variable (set by ``stixdb serve``)
          3. Current working directory
          4. Environment variables / defaults

        Use this instead of from_env() when running in a project with stixdb init.
        """
        from pathlib import Path as _Path
        if project_dir:
            base = _Path(project_dir)
        elif os.getenv("STIXDB_PROJECT_DIR"):
            base = _Path(os.environ["STIXDB_PROJECT_DIR"])
        else:
            base = _Path.cwd()

        config_path = base / ".stixdb" / "config.json"
        if config_path.exists():
            return cls.from_file(config_path)
        return cls.from_env()

    @classmethod
    def _from_config_file(cls, cf: "ConfigFile") -> "StixDBConfig":
        """Translate a ConfigFile object into a full StixDBConfig, resolving env var refs."""
        # Start from env baseline so agent tuning / backup / observability env vars still work
        base = cls.from_env()

        # ── LLM ──────────────────────────────────────────────────────────────
        llm_provider_map = {
            "openai":      LLMProvider.OPENAI,
            "anthropic":   LLMProvider.ANTHROPIC,
            "ollama":      LLMProvider.OLLAMA,
            "custom":      LLMProvider.CUSTOM,
            "none":        LLMProvider.NONE,
            # Named presets map to CUSTOM internally
            "nebius":      LLMProvider.CUSTOM,
            "openrouter":  LLMProvider.CUSTOM,
        }
        llm_provider = llm_provider_map.get(cf.llm.provider, LLMProvider.CUSTOM)

        # Resolve base_url: explicit > preset > None
        llm_base_url = cf.llm.base_url or NAMED_LLM_PRESETS.get(cf.llm.provider, {}).get("base_url")

        # Read api key directly from config.json
        llm_api_key = cf.llm.api_key or None

        base.reasoner = ReasonerConfig(
            provider=llm_provider,
            model=cf.llm.model,
            temperature=cf.llm.temperature,
            max_tokens=cf.llm.max_tokens,
            max_context_nodes=cf.llm.max_context_nodes,
            graph_traversal_depth=cf.llm.graph_traversal_depth,
            timeout_seconds=cf.llm.timeout,
            openai_api_key=llm_api_key if cf.llm.provider == "openai" else base.reasoner.openai_api_key,
            anthropic_api_key=llm_api_key if cf.llm.provider == "anthropic" else base.reasoner.anthropic_api_key,
            ollama_base_url=llm_base_url or base.reasoner.ollama_base_url,
            custom_base_url=llm_base_url if llm_provider == LLMProvider.CUSTOM else base.reasoner.custom_base_url,
            custom_api_key=llm_api_key if llm_provider == LLMProvider.CUSTOM else base.reasoner.custom_api_key,
        )

        # ── Embedding ─────────────────────────────────────────────────────────
        emb_provider_map = {
            "local":       EmbeddingProvider.SENTENCE_TRANSFORMERS,
            "openai":      EmbeddingProvider.OPENAI,
            "ollama":      EmbeddingProvider.OLLAMA,
            "custom":      EmbeddingProvider.CUSTOM,
            "nebius":      EmbeddingProvider.CUSTOM,
            "openrouter":  EmbeddingProvider.CUSTOM,
        }
        emb_provider = emb_provider_map.get(cf.embedding.provider, EmbeddingProvider.CUSTOM)
        emb_base_url = cf.embedding.base_url or NAMED_EMBEDDING_PRESETS.get(cf.embedding.provider, {}).get("base_url")
        emb_api_key = cf.embedding.api_key or None

        base.embedding = EmbeddingConfig(
            provider=emb_provider,
            model=cf.embedding.model,
            dimensions=cf.embedding.dimensions,
            openai_api_key=emb_api_key if cf.embedding.provider == "openai" else base.embedding.openai_api_key,
            ollama_base_url=emb_base_url or base.embedding.ollama_base_url,
            custom_base_url=emb_base_url if emb_provider == EmbeddingProvider.CUSTOM else base.embedding.custom_base_url,
            custom_api_key=emb_api_key if emb_provider == EmbeddingProvider.CUSTOM else base.embedding.custom_api_key,
        )

        # ── Storage ───────────────────────────────────────────────────────────
        storage_mode_map = {
            "kuzu":   StorageMode.KUZU,
            "memory": StorageMode.MEMORY,
            "neo4j":  StorageMode.NEO4J,
        }
        storage_mode = storage_mode_map.get(cf.storage.mode, StorageMode.KUZU)

        # Resolve relative/home-relative storage paths against ~/.stixdb/ so
        # data survives daemon restarts regardless of the process working directory.
        from pathlib import Path as _Path
        _raw = _Path(cf.storage.path).expanduser()
        data_dir = str(_raw if _raw.is_absolute() else _Path.home() / ".stixdb" / _raw)

        base.storage = StorageConfig(
            mode=storage_mode,
            data_dir=data_dir,
            vector_backend=base.storage.vector_backend,
            kuzu_path=os.path.join(data_dir, "kuzu"),
            kuzu_buffer_pool_mb=cf.storage.kuzu_buffer_pool_mb or base.storage.kuzu_buffer_pool_mb,
            neo4j_uri=cf.storage.neo4j_uri or base.storage.neo4j_uri,
            neo4j_user=os.getenv(cf.storage.neo4j_user_env, "neo4j") if cf.storage.neo4j_user_env else base.storage.neo4j_user,
            neo4j_password=os.getenv(cf.storage.neo4j_password_env, "password") if cf.storage.neo4j_password_env else base.storage.neo4j_password,
            qdrant_host=base.storage.qdrant_host,
            qdrant_port=base.storage.qdrant_port,
            sql_url=base.storage.sql_url,
            max_active_nodes=base.storage.max_active_nodes,
        )

        # ── Ingestion ─────────────────────────────────────────────────────────
        base.ingestion = IngestionConfig(
            default_chunk_size=cf.ingestion.chunk_size,
            default_chunk_overlap=cf.ingestion.chunk_overlap,
        )

        # ── Agent ─────────────────────────────────────────────────────────────
        base.agent = AgentConfig(
            cycle_interval_seconds=cf.agent.cycle_interval,
            consolidation_similarity_threshold=cf.agent.consolidation_threshold,
            decay_half_life_hours=cf.agent.decay_half_life_hours,
            prune_importance_threshold=cf.agent.prune_threshold,
            working_memory_max_nodes=cf.agent.working_memory_max,
            max_consolidation_batch=cf.agent.max_consolidation_batch,
            enable_auto_summarize=cf.agent.auto_summarize,
            lineage_safe_mode=cf.agent.lineage_safe_mode,
            synthesis_similarity_lower=cf.agent.synthesis_similarity_lower,
            max_synthesis_batch=cf.agent.max_synthesis_batch,
            enable_relation_weaving=cf.agent.enable_relation_weaving,
            relation_similarity_lower=cf.agent.relation_similarity_lower,
            weaver_batch_size=cf.agent.weaver_batch_size,
            weaver_batch_limit=cf.agent.weaver_batch_limit,
            enable_predictive_prefetch=cf.agent.enable_predictive_prefetch,
            prefetch_history_size=cf.agent.prefetch_history_size,
            prefetch_max_promote=cf.agent.prefetch_max_promote,
            enable_neighbor_fanout=cf.agent.enable_neighbor_fanout,
            prefetch_max_fanout=cf.agent.prefetch_max_fanout,
        )

        # ── Observability ─────────────────────────────────────────────────────
        base.enable_traces = cf.observability.enable_traces
        base.enable_metrics = cf.observability.enable_metrics
        base.metrics_port = cf.observability.metrics_port
        base.log_level = cf.observability.log_level

        # ── API server ────────────────────────────────────────────────────────
        base.api = ApiServerConfig(
            port=cf.server.port,
            api_key=cf.server.api_key or None,
        )

        return base

    @classmethod
    def from_env(cls) -> "StixDBConfig":
        """Build config from environment variables with sane defaults."""
        try:
            from dotenv import load_dotenv, find_dotenv
            load_dotenv(find_dotenv(usecwd=True))
        except ImportError:
            pass

        # Helper: treat empty-string env vars the same as unset ones.
        # os.getenv(KEY, DEFAULT) returns "" when Docker passes KEY= (empty),
        # because the variable is technically set. Using `or` collapses "" → default.
        def _e(key: str, default: str) -> str:
            return os.getenv(key) or default

        provider = LLMProvider(_e("STIXDB_LLM_PROVIDER", "openai"))
        model = _e("STIXDB_LLM_MODEL", "gpt-4o")
        storage_mode = StorageMode(_e("STIXDB_STORAGE_MODE", "memory"))
        data_dir = _e("STIXDB_DATA_DIR", "./stixdb_data")
        vector_backend = VectorBackend(_e("STIXDB_VECTOR_BACKEND", "qdrant"))

        return cls(
            agent=AgentConfig(
                cycle_interval_seconds=float(_e("STIXDB_AGENT_CYCLE_INTERVAL", "300.0")),
                consolidation_similarity_threshold=float(_e("STIXDB_AGENT_CONSOLIDATION_THRESHOLD", "0.88")),
                decay_half_life_hours=float(_e("STIXDB_AGENT_DECAY_HALF_LIFE", "48.0")),
                prune_importance_threshold=float(_e("STIXDB_AGENT_PRUNE_THRESHOLD", "0.05")),
                working_memory_max_nodes=int(_e("STIXDB_AGENT_WORKING_MEMORY_MAX", "256")),
                max_consolidation_batch=int(_e("STIXDB_AGENT_MAX_CONSOLIDATION_BATCH", "64")),
                enable_auto_summarize=_e("STIXDB_AGENT_AUTO_SUMMARIZE", "true").lower() == "true",
                lineage_safe_mode=_e("STIXDB_AGENT_LINEAGE_SAFE_MODE", "true").lower() == "true",
            ),
            reasoner=ReasonerConfig(
                provider=provider,
                model=model,
                temperature=float(_e("STIXDB_LLM_TEMPERATURE", "0.2")),
                max_tokens=int(_e("STIXDB_LLM_MAX_TOKENS", "4096")),
                max_context_nodes=int(_e("STIXDB_LLM_MAX_CONTEXT_NODES", "20")),
                graph_traversal_depth=int(_e("STIXDB_LLM_GRAPH_TRAVERSAL_DEPTH", "3")),
                timeout_seconds=float(_e("STIXDB_LLM_TIMEOUT", "60.0")),
                openai_api_key=os.getenv("OPENAI_API_KEY") or None,
                anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
                ollama_base_url=_e("OLLAMA_BASE_URL", "http://localhost:11434"),
                custom_base_url=os.getenv("STIXDB_LLM_CUSTOM_BASE_URL") or None,
                custom_api_key=os.getenv("STIXDB_LLM_CUSTOM_API_KEY") or None,
            ),
            storage=StorageConfig(
                mode=storage_mode,
                data_dir=data_dir,
                vector_backend=vector_backend,
                kuzu_path=_e("STIXDB_KUZU_PATH", os.path.join(data_dir, "kuzu")),
                kuzu_buffer_pool_mb=int(_e("STIXDB_KUZU_BUFFER_POOL_MB", "4096")),
                qdrant_host=_e("QDRANT_HOST", ""),
                qdrant_port=int(_e("QDRANT_PORT", "6333")),
                chroma_host=os.getenv("CHROMA_HOST") or None,
                neo4j_uri=_e("NEO4J_URI", "bolt://localhost:7687"),
                neo4j_user=_e("NEO4J_USER", "neo4j"),
                neo4j_password=_e("NEO4J_PASSWORD", "password"),
                sql_url=_e("STIXDB_SQL_URL", "postgresql://stixdb:stixdb_pass@localhost:5432/stixdb"),
                max_active_nodes=int(_e("STIXDB_STORAGE_MAX_ACTIVE_NODES", "1000000")),
            ),
            embedding=EmbeddingConfig(
                provider=EmbeddingProvider(_e("STIXDB_EMBEDDING_PROVIDER", "sentence_transformers")),
                model=_e("STIXDB_EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
                dimensions=int(_e("STIXDB_EMBEDDING_DIMENSIONS", "384")),
                openai_api_key=os.getenv("OPENAI_API_KEY") or None,
                ollama_base_url=_e("OLLAMA_BASE_URL", "http://localhost:11434"),
                custom_base_url=os.getenv("STIXDB_EMBEDDING_CUSTOM_BASE_URL") or None,
                custom_api_key=os.getenv("STIXDB_EMBEDDING_CUSTOM_API_KEY") or None,
            ),
            ingestion=IngestionConfig(
                default_chunk_size=int(_e("STIXDB_CHUNK_SIZE", "1000")),
                default_chunk_overlap=int(_e("STIXDB_CHUNK_OVERLAP", "200")),
            ),
            api=ApiServerConfig(
                port=int(_e("STIXDB_API_PORT", "4020")),
                api_key=os.getenv("STIXDB_API_KEY") or None,
            ),
            backup=BackupConfig(
                enabled=_e("STIXDB_BACKUP_ENABLED", "false").lower() == "true",
                endpoint=_e("STIXDB_BACKUP_MINIO_ENDPOINT", "localhost:9000"),
                access_key=_e("STIXDB_BACKUP_MINIO_ACCESS_KEY", "minioadmin"),
                secret_key=_e("STIXDB_BACKUP_MINIO_SECRET_KEY", "minioadmin"),
                bucket=_e("STIXDB_BACKUP_MINIO_BUCKET", "stixdb-ingestion"),
                secure=_e("STIXDB_BACKUP_MINIO_SECURE", "false").lower() == "true",
                prefix=_e("STIXDB_BACKUP_PREFIX", "uploads"),
            ),
            enable_traces=_e("STIXDB_ENABLE_TRACES", "true").lower() == "true",
            enable_metrics=_e("STIXDB_ENABLE_METRICS", "true").lower() == "true",
            metrics_port=int(_e("STIXDB_METRICS_PORT", "9090")),
            log_level=_e("STIXDB_LOG_LEVEL", "INFO"),
        )

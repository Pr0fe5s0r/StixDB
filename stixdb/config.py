"""
StixDB Engine Configuration.
Single source of truth for all runtime settings.
"""
from __future__ import annotations

import os
from enum import Enum
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


class ReasonerConfig(BaseModel):
    """Configuration for the LLM-backed Reasoner."""
    provider: LLMProvider = LLMProvider.OPENAI
    model: str = "gpt-4o"
    temperature: float = 0.2
    max_tokens: int = 2048
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
    vector_backend: VectorBackend = VectorBackend.MEMORY
    # KuzuDB settings (local dev, no Docker needed)
    kuzu_path: str = "./stixdb_data/kuzu"
    # Qdrant settings (docker: qdrant service)
    qdrant_host: str = "localhost"
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
        vector_backend = VectorBackend(_e("STIXDB_VECTOR_BACKEND", "memory"))

        return cls(
            agent=AgentConfig(
                cycle_interval_seconds=float(_e("STIXDB_AGENT_CYCLE_INTERVAL", "30.0")),
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
                max_tokens=int(_e("STIXDB_LLM_MAX_TOKENS", "2048")),
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
                qdrant_host=_e("QDRANT_HOST", "localhost"),
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

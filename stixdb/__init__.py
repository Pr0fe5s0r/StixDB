"""
StixDB — Reasoning Agentic Context Database Engine
"""

from stixdb.client import StixDBEngine, StixDBConfig, ContextResponse

# Internal engine classes still accessible via full module paths:
#   stixdb.engine.StixDBEngine  — in-process server engine
#   stixdb.config.StixDBConfig  — server storage/LLM config

__version__ = "0.1.0"
__all__ = [
    "StixDBEngine",
    "StixDBConfig",
    "ContextResponse",
]

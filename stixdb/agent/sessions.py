"""
Session Manager — handles short-term chat history for multi-turn conversations.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional


@dataclass
class ChatMessage:
    role: str           # "system", "user", "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


class Session:
    """A single chat session holding message history."""

    def __init__(self, session_id: str, max_history: int = 10) -> None:
        self.id = session_id
        self.messages: list[ChatMessage] = []
        self.max_history = max_history
        self.last_accessed = time.time()

    def add_message(self, role: str, content: str) -> None:
        self.messages.append(ChatMessage(role=role, content=content))
        self.last_accessed = time.time()
        # Keep only the last N messages (sliding window)
        if len(self.messages) > self.max_history:
            self.messages = self.messages[-self.max_history:]

    def get_history(self) -> list[dict]:
        return [m.to_dict() for m in self.messages]

    def clear(self) -> None:
        self.messages = []


class SessionManager:
    """
    Manages multiple chat sessions in-memory.
    Automatically prunes expired sessions.
    """

    def __init__(self, ttl_hours: int = 24) -> None:
        self._sessions: dict[str, Session] = {}
        self.ttl_hours = ttl_hours

    def get_session(self, session_id: str) -> Session:
        self._prune()
        if session_id not in self._sessions:
            self._sessions[session_id] = Session(session_id)
        return self._sessions[session_id]

    def _prune(self) -> None:
        """Remove sessions that haven't been accessed in TTL hours."""
        now = time.time()
        limit = now - (self.ttl_hours * 3600)
        expired = [sid for sid, s in self._sessions.items() if s.last_accessed < limit]
        for sid in expired:
            del self._sessions[sid]

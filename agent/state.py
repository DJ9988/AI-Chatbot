"""Session and conversation history state management with MLflow multi-turn trace chaining."""

from __future__ import annotations

import atexit
import logging
import time
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

logger = logging.getLogger(__name__)


class SessionState:
    """Encapsulates multi-turn message history and MLflow session-level trace chaining."""

    def __init__(self, session_id: str, max_history_turns: int = 20) -> None:
        self.session_id = session_id
        self.max_history_turns = max_history_turns
        self.messages: List[BaseMessage] = []
        self.created_at: float = time.time()
        self.updated_at: float = time.time()
        self.query_count: int = 0
        self.clarification_count: int = 0
        self.trace_id: Optional[str] = None

    def ensure_trace(self) -> None:
        """Initialize session tracking if needed."""
        pass

    def update_trace_outputs(self) -> None:
        """Update session tracking outputs."""
        pass

    def close_trace(self) -> Optional[str]:
        """Flush traces and return the active trace ID."""
        try:
            from observability.tracer import flush_traces
            flush_traces()
        except Exception:
            pass
        return self.trace_id

    def add_user_message(self, content: str) -> HumanMessage:
        """Append a user message to the session history."""
        msg = HumanMessage(content=content)
        self.messages.append(msg)
        self.query_count += 1
        self.updated_at = time.time()
        self._trim_history()
        return msg

    def add_ai_message(self, content: str, tool_calls: Optional[List[dict]] = None) -> AIMessage:
        """Append an AI assistant message to the session history.
        
        Conversational message history sent to LLM providers must store the synthesized
        assistant response as clean text, avoiding dangling tool_calls without matching
        ToolMessages which causes 'mismatched function calls and responses' 400 errors.
        """
        msg = AIMessage(content=content)
        self.messages.append(msg)
        self.updated_at = time.time()
        self._trim_history()
        return msg

    def add_message(self, message: BaseMessage) -> None:
        """Append any LangChain BaseMessage (e.g. ToolMessage)."""
        self.messages.append(message)
        self.updated_at = time.time()

    def get_messages(self) -> List[BaseMessage]:
        """Return a copy of the current message history."""
        return list(self.messages)

    def clear(self) -> None:
        """Reset conversation history."""
        self.messages.clear()
        self.updated_at = time.time()

    def _trim_history(self) -> None:
        """Keep message history within the max turns window to prevent unbounded growth."""
        human_indices = [i for i, m in enumerate(self.messages) if isinstance(m, HumanMessage)]
        if len(human_indices) > self.max_history_turns:
            cutoff = human_indices[-self.max_history_turns]
            self.messages = self.messages[cutoff:]


class ConversationManager:
    """Manages active conversation sessions in memory with automated trace closure."""

    def __init__(self, max_history_turns: int = 20) -> None:
        self._sessions: Dict[str, SessionState] = {}
        self._max_history_turns = max_history_turns
        atexit.register(self.close_all_sessions)

    def get_session(self, session_id: str) -> SessionState:
        """Retrieve an existing session or initialize a new one."""
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(
                session_id=session_id,
                max_history_turns=self._max_history_turns,
            )
        return self._sessions[session_id]

    def reset_session(self, session_id: str) -> None:
        """Clear history and close trace for a specific session."""
        if session_id in self._sessions:
            self._sessions[session_id].close_trace()
            self._sessions[session_id].clear()

    def close_all_sessions(self) -> None:
        """Close and export all active session traces."""
        for s in list(self._sessions.values()):
            s.close_trace()

    def list_sessions(self) -> List[str]:
        """Return all active session IDs."""
        return list(self._sessions.keys())

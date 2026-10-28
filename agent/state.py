"""Session and conversation history state management."""

from __future__ import annotations

import time
from typing import Dict, List, Optional
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage


class SessionState:
    """Encapsulates the multi-turn message history for a single conversation session."""

    def __init__(self, session_id: str, max_history_turns: int = 20) -> None:
        self.session_id = session_id
        self.max_history_turns = max_history_turns
        self.messages: List[BaseMessage] = []
        self.created_at: float = time.time()
        self.updated_at: float = time.time()
        self.query_count: int = 0
        self.clarification_count: int = 0

    def add_user_message(self, content: str) -> HumanMessage:
        """Append a user message to the session history."""
        msg = HumanMessage(content=content)
        self.messages.append(msg)
        self.query_count += 1
        self.updated_at = time.time()
        self._trim_history()
        return msg

    def add_ai_message(self, content: str, tool_calls: Optional[List[dict]] = None) -> AIMessage:
        """Append an AI assistant message to the session history."""
        kwargs = {}
        if tool_calls:
            kwargs["tool_calls"] = tool_calls
        msg = AIMessage(content=content, **kwargs)
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
        max_messages = self.max_history_turns * 2
        if len(self.messages) > max_messages:
            self.messages = self.messages[-max_messages:]


class ConversationManager:
    """Manages active conversation sessions in memory."""

    def __init__(self, max_history_turns: int = 20) -> None:
        self._sessions: Dict[str, SessionState] = {}
        self._max_history_turns = max_history_turns

    def get_session(self, session_id: str) -> SessionState:
        """Retrieve an existing session or initialize a new one."""
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(
                session_id=session_id,
                max_history_turns=self._max_history_turns,
            )
        return self._sessions[session_id]

    def reset_session(self, session_id: str) -> None:
        """Clear history for a specific session."""
        if session_id in self._sessions:
            self._sessions[session_id].clear()

    def list_sessions(self) -> List[str]:
        """Return all active session IDs."""
        return list(self._sessions.keys())


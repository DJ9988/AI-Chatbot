"""Main LangChain agent orchestrating tools, state, and cross-questioning clarification."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool

from agent.prompts import SYSTEM_PROMPT
from agent.state import ConversationManager, SessionState
from config.provider import get_chat_model
from config.settings import Settings, get_settings
from tools.db_tools import (
    filter_companies_tool,
    get_available_filters,
    lookup_company,
    search_companies_tool,
)

logger = logging.getLogger(__name__)


@dataclass
class AgentResponse:
    """Structured response returned by the UnicornAgent for each user turn."""

    content: str
    session_id: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    is_clarification: bool = False
    latency_ms: float = 0.0


class UnicornAgent:
    """Conversational agent for Indian unicorn startups using LangChain tool calling."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        model: Optional[BaseChatModel] = None,
        tools: Optional[List[BaseTool]] = None,
        conversation_manager: Optional[ConversationManager] = None,
        max_tool_iterations: int = 5,
    ) -> None:
        self.settings = settings or get_settings()
        self.model = model or get_chat_model(self.settings)
        self.tools = tools or [
            get_available_filters,
            lookup_company,
            filter_companies_tool,
            search_companies_tool,
        ]
        self.tool_map: Dict[str, BaseTool] = {t.name: t for t in self.tools}
        self.llm_with_tools = self.model.bind_tools(self.tools)
        self.conversation_manager = conversation_manager or ConversationManager()
        self.max_tool_iterations = max_tool_iterations

    def is_clarification_response(self, text: str, tool_calls_count: int = 0) -> bool:
        """Check if the response is asking a clarifying question.
        
        When the user's question is ambiguous, the agent replies directly with a clarifying
        question to the user without making unnecessary data retrieval calls.
        """
        cleaned = text.strip()
        if not cleaned:
            return False
        return tool_calls_count == 0 and cleaned.endswith("?")

    def chat(self, user_query: str, session_id: str = "default") -> AgentResponse:
        """Execute a conversation turn with history, tool execution, and clarification detection."""
        start_time = time.perf_counter()
        session = self.conversation_manager.get_session(session_id)

        # 1. Add user message to session history
        session.add_user_message(user_query)

        # 2. Build full message chain: System prompt + session messages
        current_messages: List[BaseMessage] = [
            SystemMessage(content=SYSTEM_PROMPT),
            *session.get_messages(),
        ]

        executed_tool_calls: List[Dict[str, Any]] = []
        iteration = 0

        # 3. Iterative tool-calling loop
        while iteration < self.max_tool_iterations:
            iteration += 1
            ai_msg: AIMessage = self.llm_with_tools.invoke(current_messages)
            current_messages.append(ai_msg)

            # If no tools requested, we have the final assistant reply
            if not getattr(ai_msg, "tool_calls", None):
                break

            # Execute all requested tool calls
            for tool_call in ai_msg.tool_calls:
                tool_name = tool_call.get("name", "")
                tool_args = tool_call.get("args", {})
                tool_id = tool_call.get("id", f"call_{iteration}")

                executed_tool_calls.append({
                    "name": tool_name,
                    "args": tool_args,
                    "id": tool_id,
                })

                tool = self.tool_map.get(tool_name)
                if tool is None:
                    tool_output = f"Error: Tool '{tool_name}' is not recognized."
                else:
                    try:
                        tool_output = tool.invoke(tool_args)
                    except Exception as exc:
                        logger.exception("Error executing tool %s with args %s", tool_name, tool_args)
                        tool_output = f"Tool execution error: {exc}"

                tool_msg = ToolMessage(
                    content=str(tool_output),
                    tool_call_id=tool_id,
                )
                current_messages.append(tool_msg)

        # 4. Extract final text content
        final_content = ""
        for msg in reversed(current_messages):
            if isinstance(msg, AIMessage) and msg.content:
                final_content = str(msg.content)
                break

        if not final_content:
            final_content = "I could not retrieve a response for your query. Please try rephrasing."

        # 5. Record final AI message in persistent session
        session.add_ai_message(content=final_content, tool_calls=executed_tool_calls or None)

        # 6. Check for clarification
        is_clarification = self.is_clarification_response(
            final_content, tool_calls_count=len(executed_tool_calls)
        )
        if is_clarification:
            session.clarification_count += 1

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        return AgentResponse(
            content=final_content,
            session_id=session_id,
            tool_calls=executed_tool_calls,
            is_clarification=is_clarification,
            latency_ms=round(latency_ms, 2),
        )


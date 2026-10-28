"""Main LangChain agent orchestrating tools, state, and cross-questioning clarification."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import mlflow
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from mlflow.entities import SpanType

from agent.prompts import SYSTEM_PROMPT
from agent.state import ConversationManager, SessionState
from config.provider import get_chat_model
from config.settings import Settings, get_settings
from observability.logger import get_audit_logger
from observability.metrics import get_metrics_collector
from observability.tracer import flush_traces, get_last_trace_id, get_trace_summary, init_tracer
from security.sanitizer import sanitize_query
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
    trace_id: Optional[str] = None
    token_usage: Dict[str, int] = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
    sanitized_query: str = ""
    guardrail_flags: List[str] = field(default_factory=list)
    thought: Optional[str] = None


class ThoughtStreamFilter:
    """Filters and routes stream tokens into thoughts (<think> or reasoning_content) and answer tokens."""

    def __init__(
        self,
        on_token: Optional[Callable[[str], None]] = None,
        on_thought: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.on_token = on_token
        self.on_thought = on_thought
        self.in_think = False
        self.buffer = ""
        self.collected_thoughts: List[str] = []
        self.collected_tokens: List[str] = []

    def process_chunk(self, chunk_text: str, reasoning_content: Optional[str] = None) -> None:
        if reasoning_content:
            self.collected_thoughts.append(reasoning_content)
            if self.on_thought:
                self.on_thought(reasoning_content)

        if not chunk_text:
            return

        self.buffer += chunk_text

        while self.buffer:
            if not self.in_think:
                if "<think>" in self.buffer:
                    before, _, after = self.buffer.partition("<think>")
                    if before:
                        self.collected_tokens.append(before)
                        if self.on_token:
                            self.on_token(before)
                    self.in_think = True
                    self.buffer = after
                else:
                    partial_len = 0
                    for i in range(len("<think>") - 1, 0, -1):
                        if self.buffer.endswith("<think>"[:i]):
                            partial_len = i
                            break
                    safe_len = len(self.buffer) - partial_len
                    if safe_len > 0:
                        safe_text = self.buffer[:safe_len]
                        self.collected_tokens.append(safe_text)
                        if self.on_token:
                            self.on_token(safe_text)
                        self.buffer = self.buffer[safe_len:]
                    break
            else:
                if "</think>" in self.buffer:
                    thought, _, after = self.buffer.partition("</think>")
                    if thought:
                        self.collected_thoughts.append(thought)
                        if self.on_thought:
                            self.on_thought(thought)
                    self.in_think = False
                    self.buffer = after
                else:
                    partial_len = 0
                    for i in range(len("</think>") - 1, 0, -1):
                        if self.buffer.endswith("</think>"[:i]):
                            partial_len = i
                            break
                    safe_len = len(self.buffer) - partial_len
                    if safe_len > 0:
                        safe_text = self.buffer[:safe_len]
                        self.collected_thoughts.append(safe_text)
                        if self.on_thought:
                            self.on_thought(safe_text)
                        self.buffer = self.buffer[safe_len:]
                    break

    def flush(self) -> None:
        if self.buffer:
            if self.in_think:
                self.collected_thoughts.append(self.buffer)
                if self.on_thought:
                    self.on_thought(self.buffer)
            else:
                self.collected_tokens.append(self.buffer)
                if self.on_token:
                    self.on_token(self.buffer)
            self.buffer = ""

    def get_thought(self) -> str:
        return "".join(self.collected_thoughts).strip()

    def get_clean_content(self) -> str:
        return "".join(self.collected_tokens).strip()


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
        init_tracer(self.settings)
        self.audit_logger = get_audit_logger()
        self.metrics_collector = get_metrics_collector()
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

    def chat(
        self,
        user_query: str,
        session_id: str = "default",
        on_token: Optional[Callable[[str], None]] = None,
        on_thought: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_tool_start: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        on_tool_end: Optional[Callable[[str, str, float], None]] = None,
    ) -> AgentResponse:
        """Execute a conversation turn nested within the multi-turn session trace.

        Supports real-time token streaming, thinking tokens, and tool progress reporting.
        """
        start_time = time.perf_counter()

        session = self.conversation_manager.get_session(session_id)
        session.ensure_trace()

        turn_index = session.query_count + 1

        # 1. Input sanitization & guardrail check (Requirement 4)
        sanitized = sanitize_query(user_query)
        effective_query = sanitized.sanitized_query
        guardrail_flags = sanitized.flagged_reasons or []

        if not sanitized.is_safe:
            refusal_content = (
                "I cannot fulfill this request. I am only authorized to answer questions "
                "about Indian unicorn startups from the database."
            )
            session.add_user_message(effective_query)
            session.add_ai_message(refusal_content)
            session.update_trace_outputs()
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            trace_id = session.trace_id or get_last_trace_id()
            token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

            if on_token:
                on_token(refusal_content)

            self.audit_logger.log_turn(
                session_id=session_id,
                turn_index=session.query_count,
                user_query=user_query,
                sanitized_query=effective_query,
                is_safe=False,
                guardrail_flags=guardrail_flags,
                bot_response=refusal_content,
                latency_ms=latency_ms,
                tool_calls=[],
                is_clarification=False,
                trace_id=trace_id,
                model=self.settings.primary_model,
                token_usage=token_usage,
                error="Prompt injection detected and blocked by guardrail.",
            )
            self.metrics_collector.record_turn(
                session_id=session_id,
                latency_ms=latency_ms,
                is_clarification=False,
                error=False,
                is_flagged=True,
                tool_names=[],
                token_usage=token_usage,
            )
            return AgentResponse(
                content=refusal_content,
                session_id=session_id,
                tool_calls=[],
                is_clarification=False,
                latency_ms=round(latency_ms, 2),
                trace_id=trace_id,
                token_usage=token_usage,
                sanitized_query=effective_query,
                guardrail_flags=guardrail_flags,
                thought=None,
            )

        # 2. Add user message to session history
        session.add_user_message(effective_query)
        session_len_at_start = len(session.messages)

        # 3. Build full message chain: System prompt + session messages
        current_messages: List[BaseMessage] = [
            SystemMessage(content=SYSTEM_PROMPT),
            *session.get_messages(),
        ]

        executed_tool_calls: List[Dict[str, Any]] = []
        iteration = 0
        turn_error: Optional[str] = None
        total_input_tokens = 0
        total_output_tokens = 0
        used_model_name = self.settings.primary_model
        final_content = ""
        final_thought = ""

        # 4. Execute turn inside Turn span (nested under Session root span)
        with mlflow.start_span(
            name=f"Turn {turn_index}: {effective_query[:40]}", span_type=SpanType.CHAIN
        ) as turn_span:
            turn_span.set_inputs({
                "user_query": user_query,
                "sanitized_query": effective_query,
                "turn_index": turn_index,
            })

            # Multi-step ReAct loop
            while iteration < self.max_tool_iterations:
                iteration += 1

                # Decide whether to call model with tools or synthesize final response
                needs_synthesis = False
                if executed_tool_calls:
                    last_call = executed_tool_calls[-1]
                    # get_available_filters is an auxiliary tool for discovering valid filters;
                    # after inspecting filters, the agent still needs to query with the chosen filter
                    if last_call.get("name") != "get_available_filters" and (
                        last_call.get("status") == "success" or iteration >= self.max_tool_iterations
                    ):
                        needs_synthesis = True

                invoker = self.model if needs_synthesis else self.llm_with_tools

                if on_status:
                    if executed_tool_calls:
                        on_status("Synthesizing answer from retrieved startup data...")
                    else:
                        on_status("Analyzing query & evaluating required startup tools...")

                stream_filter = ThoughtStreamFilter(on_token=on_token, on_thought=on_thought)

                try:
                    if (on_token is not None or on_thought is not None) and hasattr(invoker, "stream"):
                        # Real-time token streaming with live thought extraction
                        accumulated_msg: Optional[AIMessageChunk] = None
                        for chunk in invoker.stream(current_messages):
                            accumulated_msg = chunk if accumulated_msg is None else accumulated_msg + chunk
                            reasoning = (
                                chunk.additional_kwargs.get("reasoning_content")
                                if hasattr(chunk, "additional_kwargs") and chunk.additional_kwargs
                                else None
                            )
                            stream_filter.process_chunk(str(chunk.content or ""), reasoning_content=reasoning)
                        stream_filter.flush()
                        ai_msg = accumulated_msg or AIMessage(content="")
                    else:
                        ai_msg = invoker.invoke(current_messages)
                except Exception as exc:
                    if on_token is not None or on_thought is not None:
                        # Fallback to invoke if mock or model does not implement stream
                        try:
                            ai_msg = invoker.invoke(current_messages)
                            stream_filter.process_chunk(str(ai_msg.content or ""))
                            stream_filter.flush()
                        except Exception as inner_exc:
                            logger.error("LLM invocation error: %s", inner_exc)
                            turn_error = str(inner_exc)
                            break
                    else:
                        logger.error("LLM invocation error: %s", exc)
                        turn_error = str(exc)
                        break

                current_messages.append(ai_msg)

                # Accumulate token metrics
                if hasattr(ai_msg, "usage_metadata") and ai_msg.usage_metadata:
                    total_input_tokens += ai_msg.usage_metadata.get("input_tokens", 0)
                    total_output_tokens += ai_msg.usage_metadata.get("output_tokens", 0)
                if hasattr(ai_msg, "response_metadata") and ai_msg.response_metadata:
                    model_meta = ai_msg.response_metadata.get("model_name")
                    if model_meta:
                        used_model_name = str(model_meta)

                # Extract cleaned content and thoughts
                clean_text = stream_filter.get_clean_content()
                thought_text = stream_filter.get_thought()
                if not clean_text and ai_msg.content:
                    raw_str = str(ai_msg.content)
                    if "<think>" in raw_str and "</think>" in raw_str:
                        thought_part, _, after = raw_str.partition("</think>")
                        _, _, th_content = thought_part.partition("<think>")
                        thought_text = th_content.strip()
                        clean_text = after.strip()
                    else:
                        clean_text = raw_str.strip()

                if thought_text:
                    final_thought = (f"{final_thought}\n{thought_text}").strip() if final_thought else thought_text

                tool_calls = getattr(ai_msg, "tool_calls", None)

                # If no tools requested or synthesis yielded text, we have our final content
                if not tool_calls:
                    if clean_text:
                        final_content = clean_text
                    elif ai_msg.content:
                        final_content = str(ai_msg.content)
                    break
                elif needs_synthesis and (clean_text or ai_msg.content):
                    final_content = clean_text or str(ai_msg.content)
                    break

                # Execute all requested tool calls
                for tool_call in tool_calls:
                    tool_name = tool_call.get("name", "")
                    tool_args = tool_call.get("args", {})
                    tool_id = tool_call.get("id", f"call_{iteration}")

                    if on_tool_start:
                        on_tool_start(tool_name, tool_args)

                    t0 = time.perf_counter()
                    tool = self.tool_map.get(tool_name)
                    status = "success"

                    if tool is None:
                        tool_output = f"Error: Tool '{tool_name}' is not recognized."
                        status = "error"
                    else:
                        try:
                            tool_output = tool.invoke(tool_args)
                            if isinstance(tool_output, str) and '"status": "no_results"' in tool_output:
                                status = "no_results"
                            elif isinstance(tool_output, str) and '"status": "not_found"' in tool_output:
                                status = "not_found"
                        except Exception as exc:
                            logger.exception("Error executing tool %s with args %s", tool_name, tool_args)
                            tool_output = f"Tool execution error: {exc}"
                            status = "error"

                    tool_duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)

                    if on_tool_end:
                        on_tool_end(tool_name, status, tool_duration_ms)

                    executed_tool_calls.append({
                        "name": tool_name,
                        "args": tool_args,
                        "id": tool_id,
                        "duration_ms": tool_duration_ms,
                        "status": status,
                    })

                    tool_msg = ToolMessage(
                        content=str(tool_output),
                        tool_call_id=tool_id,
                    )
                    current_messages.append(tool_msg)

                # If max iterations reached, invoke model once more for final synthesis
                if iteration >= self.max_tool_iterations:
                    try:
                        synth_msg = self.model.invoke(current_messages)
                        current_messages.append(synth_msg)
                        final_content = str(synth_msg.content or "")
                    except Exception as exc:
                        logger.error("Synthesis invocation error: %s", exc)
                    break

            # Fallback if final_content is still empty
            if not final_content:
                for msg in reversed(current_messages):
                    if isinstance(msg, AIMessage) and msg.content:
                        final_content = str(msg.content)
                        break

            if not final_content:
                if turn_error:
                    final_content = f"An error occurred while processing your request: {turn_error}"
                else:
                    final_content = "I could not retrieve a response for your query. Please try rephrasing."

            # Check for clarification
            is_clarification = self.is_clarification_response(
                final_content, tool_calls_count=len(executed_tool_calls)
            )
            if is_clarification:
                session.clarification_count += 1

            turn_span.set_outputs({
                "bot_response": final_content,
                "thought": final_thought or None,
                "is_clarification": is_clarification,
                "tool_calls_count": len(executed_tool_calls),
            })

        # 5. Record full turn trajectory (tool calls & responses) and final AI response in session
        new_turn_messages = current_messages[1 + session_len_at_start:]
        for msg in new_turn_messages:
            if isinstance(msg, ToolMessage):
                session.add_message(msg)
            elif isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                clean_calls = [
                    {k: v for k, v in tc.items() if k in ("name", "args", "id", "type")}
                    for tc in msg.tool_calls
                ]
                session.add_message(AIMessage(content=msg.content or "", tool_calls=clean_calls))

        session.add_ai_message(content=final_content)
        session.update_trace_outputs()

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        trace_id = session.trace_id or get_last_trace_id()

        total_tokens = total_input_tokens + total_output_tokens
        token_usage = {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "total_tokens": total_tokens,
        }

        # 6. Structured Audit Logging (Requirement 5)
        self.audit_logger.log_turn(
            session_id=session_id,
            turn_index=session.query_count,
            user_query=user_query,
            sanitized_query=effective_query,
            is_safe=sanitized.is_safe,
            guardrail_flags=guardrail_flags,
            bot_response=final_content,
            latency_ms=latency_ms,
            tool_calls=executed_tool_calls,
            is_clarification=is_clarification,
            trace_id=trace_id,
            model=used_model_name,
            token_usage=token_usage,
            error=turn_error,
        )

        # 7. Metrics Collection (Requirement 6)
        self.metrics_collector.record_turn(
            session_id=session_id,
            latency_ms=latency_ms,
            is_clarification=is_clarification,
            error=bool(turn_error),
            is_flagged=not sanitized.is_safe,
            tool_names=[t["name"] for t in executed_tool_calls],
            token_usage=token_usage,
        )

        return AgentResponse(
            content=final_content,
            session_id=session_id,
            tool_calls=executed_tool_calls,
            is_clarification=is_clarification,
            latency_ms=round(latency_ms, 2),
            trace_id=trace_id,
            token_usage=token_usage,
            sanitized_query=effective_query,
            guardrail_flags=guardrail_flags,
            thought=final_thought or None,
        )

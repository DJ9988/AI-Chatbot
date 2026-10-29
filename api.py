"""FastAPI application for Indian Unicorn Startups AI Chatbot.

Provides REST and Server-Sent Event (SSE) streaming endpoints for factual lookup,
filtering, multi-turn conversations, clarification handling, and observability.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from agent.agent import UnicornAgent
from config.settings import Settings, get_settings
from observability.tracer import flush_traces, get_trace_url, init_tracer

# Global agent singleton
_AGENT: Optional[UnicornAgent] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for startup initialization and graceful shutdown."""
    global _AGENT
    settings = get_settings()
    init_tracer(settings)
    _AGENT = UnicornAgent(settings=settings)
    yield
    # Shutdown hook: flush traces and close active sessions
    if _AGENT is not None:
        _AGENT.conversation_manager.close_all_sessions()
    flush_traces()


def get_agent() -> UnicornAgent:
    """Dependency helper to get or initialize agent instance."""
    global _AGENT
    if _AGENT is None:
        settings = get_settings()
        _AGENT = UnicornAgent(settings=settings)
    return _AGENT


app = FastAPI(
    title="Indian Unicorn Startups AI Chatbot API",
    description=(
        "Production GenAI REST & SSE Streaming API powered by LangChain, SQLite FTS5, "
        "and Langfuse Observability. Answers factual queries, filters by sector/location, "
        "and handles ambiguous queries with clarifying cross-questions."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS support for web and mobile frontends
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request / Response Models ---


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, description="User query about Indian unicorn startups")
    session_id: Optional[str] = Field(
        None, description="Session ID for multi-turn conversation. Generated if omitted."
    )


class ToolCallInfo(BaseModel):
    name: str
    args: Dict[str, Any]
    duration_ms: float
    status: str


class ChatResponse(BaseModel):
    session_id: str
    turn_index: int
    query: str
    response: str
    is_clarification: bool
    thought_process: Optional[str] = None
    latency_ms: float
    tool_calls: List[ToolCallInfo] = Field(default_factory=list)
    token_usage: Dict[str, int] = Field(default_factory=dict)
    trace_id: Optional[str] = None
    trace_url: Optional[str] = None


class MessageItem(BaseModel):
    role: str
    content: str


class SessionHistoryResponse(BaseModel):
    session_id: str
    query_count: int
    clarification_count: int
    messages: List[MessageItem]


class ResetResponse(BaseModel):
    status: str
    session_id: str
    message: str


class HealthResponse(BaseModel):
    status: str
    database_status: str
    total_companies: int
    primary_model: str
    langfuse_configured: bool
    active_sessions_count: int


# --- API Endpoints ---


@app.get("/health", response_model=HealthResponse, tags=["System"])
def health_check() -> HealthResponse:
    """Verify API, database connectivity, and configuration."""
    agent = get_agent()
    settings = agent.settings

    # Verify SQLite database
    db_status = "unhealthy"
    company_count = 0
    try:
        db_file = settings.db_path
        if db_file.exists():
            with sqlite3.connect(db_file) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM companies")
                row = cursor.fetchone()
                if row and row[0] > 0:
                    company_count = row[0]
                    db_status = "healthy"
    except Exception:
        db_status = "error"

    return HealthResponse(
        status="healthy" if db_status == "healthy" else "degraded",
        database_status=db_status,
        total_companies=company_count,
        primary_model=settings.primary_model,
        langfuse_configured=settings.is_langfuse_configured,
        active_sessions_count=len(agent.conversation_manager.list_sessions()),
    )


@app.post("/chat", response_model=ChatResponse, tags=["Chat"])
def chat(request: ChatRequest) -> ChatResponse:
    """Process a user query in a synchronous turn with full metadata and tool trajectory."""
    agent = get_agent()
    session_id = request.session_id or str(uuid.uuid4())

    turn_response = agent.chat(user_query=request.query, session_id=session_id)

    tool_infos = [
        ToolCallInfo(
            name=tc.get("name", ""),
            args=tc.get("args", {}),
            duration_ms=tc.get("duration_ms", 0.0),
            status=tc.get("status", "success"),
        )
        for tc in turn_response.tool_calls
    ]

    session = agent.conversation_manager.get_session(session_id)
    trace_url = get_trace_url(turn_response.trace_id) if turn_response.trace_id else None

    return ChatResponse(
        session_id=session_id,
        turn_index=session.query_count,
        query=request.query,
        response=turn_response.content,
        is_clarification=turn_response.is_clarification,
        thought_process=turn_response.thought or None,
        latency_ms=round(turn_response.latency_ms, 2),
        tool_calls=tool_infos,
        token_usage=turn_response.token_usage,
        trace_id=turn_response.trace_id,
        trace_url=trace_url,
    )


@app.post("/chat/stream", tags=["Chat"])
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Stream live tokens, thoughts, and status updates via Server-Sent Events (SSE)."""
    agent = get_agent()
    session_id = request.session_id or str(uuid.uuid4())

    queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def on_thought(thought_chunk: str) -> None:
        loop.call_soon_threadsafe(
            queue.put_nowait, {"type": "thought", "content": thought_chunk}
        )

    def on_token(token_chunk: str) -> None:
        loop.call_soon_threadsafe(
            queue.put_nowait, {"type": "token", "content": token_chunk}
        )

    def on_status(status_msg: str) -> None:
        loop.call_soon_threadsafe(
            queue.put_nowait, {"type": "status", "content": status_msg}
        )

    def on_tool_start(name: str, args: Dict[str, Any]) -> None:
        loop.call_soon_threadsafe(
            queue.put_nowait, {"type": "tool_start", "name": name, "args": args}
        )

    def on_tool_end(name: str, status: str, duration_ms: float) -> None:
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {"type": "tool_end", "name": name, "status": status, "duration_ms": duration_ms},
        )

    async def run_chat() -> None:
        try:
            resp = await asyncio.to_thread(
                agent.chat,
                user_query=request.query,
                session_id=session_id,
                on_token=on_token,
                on_thought=on_thought,
                on_status=on_status,
                on_tool_start=on_tool_start,
                on_tool_end=on_tool_end,
            )
            session = agent.conversation_manager.get_session(session_id)
            trace_url = get_trace_url(resp.trace_id) if resp.trace_id else None
            await queue.put({
                "type": "done",
                "session_id": session_id,
                "turn_index": session.query_count,
                "is_clarification": resp.is_clarification,
                "latency_ms": round(resp.latency_ms, 2),
                "token_usage": resp.token_usage,
                "trace_id": resp.trace_id,
                "trace_url": trace_url,
            })
        except Exception as exc:
            await queue.put({"type": "error", "error": str(exc)})
        finally:
            await asyncio.sleep(0.02)
            await queue.put(None)  # Sentinel to end stream

    # Launch background task
    asyncio.create_task(run_chat())

    async def event_generator() -> AsyncGenerator[str, None]:
        # Initial connect event
        yield f"event: start\ndata: {json.dumps({'session_id': session_id})}\n\n"
        while True:
            item = await queue.get()
            if item is None:
                break
            event_type = item.get("type", "message")
            payload = json.dumps(item)
            yield f"event: {event_type}\ndata: {payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/sessions", response_model=List[str], tags=["Sessions"])
def list_sessions() -> List[str]:
    """List all active in-memory session IDs."""
    agent = get_agent()
    return agent.conversation_manager.list_sessions()


@app.get("/sessions/{session_id}", response_model=SessionHistoryResponse, tags=["Sessions"])
def get_session_history(session_id: str) -> SessionHistoryResponse:
    """Retrieve full conversational turn history for a given session."""
    agent = get_agent()
    session = agent.conversation_manager.get_session(session_id)
    messages: List[MessageItem] = []
    for msg in session.get_messages():
        role = "user" if msg.__class__.__name__ == "HumanMessage" else "assistant"
        content = str(msg.content or "")
        if content:
            messages.append(MessageItem(role=role, content=content))

    return SessionHistoryResponse(
        session_id=session_id,
        query_count=session.query_count,
        clarification_count=session.clarification_count,
        messages=messages,
    )


@app.post("/sessions/{session_id}/reset", response_model=ResetResponse, tags=["Sessions"])
def reset_session(session_id: str) -> ResetResponse:
    """Clear conversation history and flush traces for a specific session."""
    agent = get_agent()
    agent.conversation_manager.reset_session(session_id)
    return ResetResponse(
        status="success",
        session_id=session_id,
        message="Session conversation history reset successfully.",
    )


@app.get("/metrics", tags=["Observability"])
def get_metrics() -> Dict[str, Any]:
    """Return aggregated runtime metrics (queries, clarifications, latencies, tokens)."""
    agent = get_agent()
    return agent.metrics_collector.get_summary()


@app.get("/logs/latest", tags=["Observability"])
def get_latest_log(n: int = Query(1, ge=1, le=50)) -> List[Dict[str, Any]]:
    """Return the last N structured JSON audit log records."""
    agent = get_agent()
    return agent.audit_logger.get_recent_logs(limit=n)

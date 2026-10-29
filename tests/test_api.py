"""Unit tests for FastAPI application endpoints."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from agent.agent import AgentResponse
from api import app, get_agent


@pytest.fixture
def client():
    """Create FastAPI test client."""
    return TestClient(app)


def test_health_endpoint(client):
    """Verify /health endpoint returns system and database status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "database_status" in data
    assert "total_companies" in data
    assert "primary_model" in data
    assert "langfuse_configured" in data


def test_chat_endpoint_mocked(client):
    """Verify /chat endpoint processes user request and formats response correctly."""
    mock_turn = AgentResponse(
        content="Razorpay is an online payment gateway for businesses.",
        session_id="api_test_sess_1",
        tool_calls=[
            {
                "name": "lookup_company",
                "args": {"company_name": "Razorpay"},
                "duration_ms": 12.5,
                "status": "success",
            }
        ],
        is_clarification=False,
        latency_ms=120.5,
        trace_id="test_trace_123",
        token_usage={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        thought="User asked about Razorpay, looked up database.",
    )

    with patch.object(get_agent(), "chat", return_value=mock_turn):
        payload = {"query": "What does Razorpay do?", "session_id": "api_test_sess_1"}
        response = client.post("/chat", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "api_test_sess_1"
        assert data["response"] == "Razorpay is an online payment gateway for businesses."
        assert data["is_clarification"] is False
        assert len(data["tool_calls"]) == 1
        assert data["tool_calls"][0]["name"] == "lookup_company"
        assert data["token_usage"]["total_tokens"] == 150
        assert data["trace_id"] == "test_trace_123"


def test_chat_stream_endpoint_mocked(client):
    """Verify /chat/stream returns Server-Sent Events."""
    mock_turn = AgentResponse(
        content="Streamed response content",
        session_id="stream_sess_1",
        tool_calls=[],
        is_clarification=False,
        latency_ms=80.0,
        trace_id="stream_trace_456",
        token_usage={"total_tokens": 80},
        thought="Thinking...",
    )

    def fake_chat(*args, **kwargs):
        on_token = kwargs.get("on_token")
        on_thought = kwargs.get("on_thought")
        if on_thought:
            on_thought("Analyzing request...")
        if on_token:
            on_token("Streamed ")
            on_token("response")
        return mock_turn

    with patch.object(get_agent(), "chat", side_effect=fake_chat):
        payload = {"query": "Test streaming", "session_id": "stream_sess_1"}
        response = client.post("/chat/stream", json=payload)
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        text = response.text
        assert "event: start" in text
        assert "event: token" in text
        assert "event: done" in text


def test_session_history_and_reset(client):
    """Verify session message history retrieval and reset endpoint."""
    agent = get_agent()
    session = agent.conversation_manager.get_session("hist_test_sess")
    session.add_user_message("Hello from user")
    session.add_ai_message("Hello from bot")

    # Get history
    hist_resp = client.get("/sessions/hist_test_sess")
    assert hist_resp.status_code == 200
    hist_data = hist_resp.json()
    assert hist_data["session_id"] == "hist_test_sess"
    assert len(hist_data["messages"]) == 2
    assert hist_data["messages"][0]["role"] == "user"
    assert hist_data["messages"][0]["content"] == "Hello from user"
    assert hist_data["messages"][1]["role"] == "assistant"
    assert hist_data["messages"][1]["content"] == "Hello from bot"

    # Reset session
    reset_resp = client.post("/sessions/hist_test_sess/reset")
    assert reset_resp.status_code == 200
    assert reset_resp.json()["status"] == "success"

    # Verify history is now empty
    empty_resp = client.get("/sessions/hist_test_sess")
    assert len(empty_resp.json()["messages"]) == 0


def test_sessions_list(client):
    """Verify /sessions lists active sessions."""
    agent = get_agent()
    agent.conversation_manager.get_session("sess_alpha")
    response = client.get("/sessions")
    assert response.status_code == 200
    sessions = response.json()
    assert isinstance(sessions, list)
    assert "sess_alpha" in sessions


def test_metrics_endpoint(client):
    """Verify /metrics returns runtime aggregated metrics."""
    response = client.get("/metrics")
    assert response.status_code == 200
    metrics = response.json()
    assert "total_queries" in metrics
    assert "total_clarifications" in metrics
    assert "total_errors" in metrics


def test_latest_logs_endpoint(client):
    """Verify /logs/latest returns audit records."""
    response = client.get("/logs/latest?n=2")
    assert response.status_code == 200
    logs = response.json()
    assert isinstance(logs, list)

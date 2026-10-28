"""Unit tests for the UnicornAgent and conversation state management."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agent.agent import AgentResponse, UnicornAgent
from agent.prompts import SYSTEM_PROMPT
from agent.state import ConversationManager, SessionState


# ============================================================================
# 1. Session State and Conversation Manager Tests
# ============================================================================


def test_session_state_lifecycle():
    """Verify session message storage and query counting."""
    session = SessionState(session_id="test_session", max_history_turns=5)
    assert session.session_id == "test_session"
    assert session.query_count == 0
    assert len(session.get_messages()) == 0

    # Add user message
    user_msg = session.add_user_message("Hello")
    assert isinstance(user_msg, HumanMessage)
    assert session.query_count == 1
    assert len(session.get_messages()) == 1

    # Add AI message
    ai_msg = session.add_ai_message("Hi there!")
    assert isinstance(ai_msg, AIMessage)
    assert len(session.get_messages()) == 2

    # Clear session
    session.clear()
    assert len(session.get_messages()) == 0
    # Query count is retained for analytics
    assert session.query_count == 1


def test_session_history_trimming():
    """Verify that history is capped at max_history_turns * 2 messages."""
    session = SessionState(session_id="trim_session", max_history_turns=3)
    # Add 10 turns (20 messages)
    for i in range(10):
        session.add_user_message(f"User {i}")
        session.add_ai_message(f"Bot {i}")

    messages = session.get_messages()
    # Should be capped at 3 * 2 = 6 messages
    assert len(messages) == 6
    assert messages[-1].content == "Bot 9"


def test_conversation_manager_multiple_sessions():
    """Verify isolation between different session IDs."""
    mgr = ConversationManager()
    sess1 = mgr.get_session("user_1")
    sess2 = mgr.get_session("user_2")

    sess1.add_user_message("Query 1 from user 1")
    sess2.add_user_message("Query 1 from user 2")

    assert len(sess1.get_messages()) == 1
    assert sess1.get_messages()[0].content == "Query 1 from user 1"
    assert len(sess2.get_messages()) == 1
    assert sess2.get_messages()[0].content == "Query 1 from user 2"

    mgr.reset_session("user_1")
    assert len(sess1.get_messages()) == 0
    assert len(sess2.get_messages()) == 1


# ============================================================================
# 2. Clarification Detection Tests
# ============================================================================


def test_is_clarification_response():
    """Verify detection of clarifying questions vs factual answers."""
    agent = UnicornAgent(model=MagicMock())

    # Clarification samples (no tools called, direct question to user)
    assert agent.is_clarification_response(
        "Can you clarify the type of collaboration you are looking for (e.g. payments, logistics)?",
        tool_calls_count=0,
    )
    assert agent.is_clarification_response(
        "Could you specify which sector or city you are interested in?",
        tool_calls_count=0,
    )
    assert agent.is_clarification_response(
        "What kind of startups are you looking for?",
        tool_calls_count=0,
    )

    # When tools were called, it is a factual answer, not a clarification prompt
    assert not agent.is_clarification_response(
        "Razorpay was founded in 2014. Would you like to know its investors?",
        tool_calls_count=1,
    )

    # Declarative responses without question mark
    assert not agent.is_clarification_response(
        "Razorpay is an Indian fintech unicorn based in Bengaluru.",
        tool_calls_count=0,
    )
    assert not agent.is_clarification_response("", tool_calls_count=0)


# ============================================================================
# 3. Agent Execution with Mocked LLM (Tools & Multi-Turn)
# ============================================================================


def test_agent_direct_response_without_tools():
    """Verify execution when LLM replies directly without calling tools (e.g. clarification)."""
    mock_llm = MagicMock()
    # Mock LLM to return a direct clarifying question
    mock_llm.invoke.return_value = AIMessage(
        content="Could you clarify the type of collaboration you have in mind?"
    )

    # Mock bind_tools to return mock_llm itself
    mock_model = MagicMock()
    mock_model.bind_tools.return_value = mock_llm

    agent = UnicornAgent(model=mock_model)
    resp = agent.chat("Which company is best to collaborate with?", session_id="test_clarify")

    assert resp.content == "Could you clarify the type of collaboration you have in mind?"
    assert resp.is_clarification is True
    assert len(resp.tool_calls) == 0
    assert resp.latency_ms >= 0


def test_agent_tool_calling_execution():
    """Verify agent executes tool call and uses tool result to synthesize response."""
    mock_llm = MagicMock()

    # Step 1: Model requests a tool call to lookup_company
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[{
            "name": "lookup_company",
            "args": {"company_name": "Razorpay"},
            "id": "call_123",
        }],
    )
    # Step 2: Model returns final synthesized answer after receiving tool response
    final_answer_msg = AIMessage(
        content="Razorpay is an Indian payments unicorn founded in 2014 and based in Bengaluru."
    )

    mock_llm.invoke.return_value = tool_call_msg
    mock_model = MagicMock()
    mock_model.bind_tools.return_value = mock_llm
    mock_model.invoke.return_value = final_answer_msg

    agent = UnicornAgent(model=mock_model)
    resp = agent.chat("What does Razorpay do?", session_id="test_tool_session")

    assert "Razorpay is an Indian payments unicorn" in resp.content
    assert resp.is_clarification is False
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0]["name"] == "lookup_company"
    assert resp.tool_calls[0]["args"] == {"company_name": "Razorpay"}


def test_agent_multi_turn_history_persistence():
    """Verify that multi-turn interactions preserve previous turns in the session."""
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = [
        AIMessage(content="Here are 10 fintech startups."),
        AIMessage(content="Of those, 4 are based in Bengaluru: Razorpay, CRED, ..."),
    ]
    mock_model = MagicMock()
    mock_model.bind_tools.return_value = mock_llm

    agent = UnicornAgent(model=mock_model)
    session_id = "multi_turn_test"

    # Turn 1
    resp1 = agent.chat("Tell me about fintech unicorns", session_id=session_id)
    assert resp1.content == "Here are 10 fintech startups."

    # Turn 2
    resp2 = agent.chat("Which of these are based in Bangalore?", session_id=session_id)
    assert "based in Bengaluru" in resp2.content

    # Inspect session history
    session = agent.conversation_manager.get_session(session_id)
    history = session.get_messages()
    # Turn 1: 1 User + 1 AI, Turn 2: 1 User + 1 AI = 4 messages
    assert len(history) == 4
    assert history[0].content == "Tell me about fintech unicorns"
    assert history[1].content == "Here are 10 fintech startups."
    assert history[2].content == "Which of these are based in Bangalore?"
    assert "based in Bengaluru" in history[3].content


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__]))


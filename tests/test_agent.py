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

    mock_llm.invoke.side_effect = [tool_call_msg, final_answer_msg]
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


def test_agent_multi_turn_tool_calling_history_clean():
    """Verify that turns with tool calls do not leave dangling tool_calls in session history.
    
    Prevents HTTP 400 'Not the same number of function calls and responses' on follow-up turns.
    """
    mock_llm = MagicMock()
    mock_model = MagicMock()
    mock_model.bind_tools.return_value = mock_llm

    # Turn 1: Step 1 (llm_with_tools) emits tool call, Step 2 (model) synthesizes response
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[{"name": "lookup_company", "args": {"company_name": "Razorpay"}, "id": "call_1"}],
    )
    synthesis_msg = AIMessage(content="Razorpay is an Indian payments unicorn based in Bengaluru.")
    mock_llm.invoke.side_effect = [tool_call_msg]
    mock_model.invoke.side_effect = [
        synthesis_msg,
        AIMessage(content="Similar companies to Razorpay include Pine Labs, BharatPe, and CRED."),
    ]

    agent = UnicornAgent(model=mock_model)
    session_id = "test_multi_turn_tool_clean"

    # Turn 1: User asks about Razorpay (triggers tool call & synthesis)
    resp1 = agent.chat("What does Razorpay do?", session_id=session_id)
    assert "Razorpay is an Indian payments unicorn" in resp1.content
    assert len(resp1.tool_calls) == 1

    # Verify session history for Turn 1 contains clean AIMessage with no dangling tool_calls
    session = agent.conversation_manager.get_session(session_id)
    history = session.get_messages()
    assert len(history) == 2
    assert not getattr(history[1], "tool_calls", None)

    # Turn 2: User asks follow-up query
    # In Turn 2, since needs_synthesis is initially False, invoker is llm_with_tools (mock_llm)
    mock_llm.invoke.side_effect = [
        AIMessage(content="Similar companies to Razorpay include Pine Labs, BharatPe, and CRED.")
    ]
    resp2 = agent.chat("Can you find me similar companies to this one.", session_id=session_id)
    assert "Pine Labs" in resp2.content

    # Inspect messages passed to the LLM on Turn 2
    # mock_llm was called on Turn 1 step 1, and Turn 2 step 1
    turn2_input_messages = mock_llm.invoke.call_args_list[-1][0][0]
    # Check that any AIMessage in previous turns passed to LLM does NOT contain dangling tool_calls
    for msg in turn2_input_messages:
        if isinstance(msg, AIMessage):
            assert not getattr(msg, "tool_calls", None), "Found dangling tool_calls in multi-turn history sent to provider!"


def test_agent_streaming_callbacks():
    """Verify that on_token and on_tool callbacks receive live events during execution."""
    from langchain_core.messages import AIMessageChunk

    mock_llm = MagicMock()
    # Model requests a tool call in step 1 via streaming chunk
    tool_chunk = AIMessageChunk(
        content="",
        tool_call_chunks=[{
            "name": "lookup_company",
            "args": '{"company_name": "Razorpay"}',
            "id": "call_stream_1",
            "index": 0,
        }],
    )
    mock_llm.stream.return_value = [tool_chunk]

    # Model streams chunks in step 2 (synthesis)
    chunk1 = AIMessageChunk(content="Razorpay ")
    chunk2 = AIMessageChunk(content="is a fintech ")
    chunk3 = AIMessageChunk(content="unicorn.")
    mock_model = MagicMock()
    mock_model.bind_tools.return_value = mock_llm
    mock_model.stream.return_value = [chunk1, chunk2, chunk3]

    tokens_streamed = []
    tools_started = []
    tools_ended = []

    def on_token(token: str):
        tokens_streamed.append(token)

    def on_tool_start(name: str, args: dict):
        tools_started.append((name, args))

    def on_tool_end(name: str, status: str, duration_ms: float):
        tools_ended.append((name, status, duration_ms))

    agent = UnicornAgent(model=mock_model)
    resp = agent.chat(
        "What does Razorpay do?",
        session_id="stream_test_session",
        on_token=on_token,
        on_tool_start=on_tool_start,
        on_tool_end=on_tool_end,
    )

    assert "".join(tokens_streamed) == "Razorpay is a fintech unicorn."
    assert resp.content == "Razorpay is a fintech unicorn."
    assert len(tools_started) == 1
    assert tools_started[0][0] == "lookup_company"
    assert len(tools_ended) == 1
    assert tools_ended[0][0] == "lookup_company"
    assert tools_ended[0][1] == "success"


def test_thought_streaming_with_tags_and_reasoning_content():
    """Verify live routing of both <think> tags and native reasoning_content to on_thought callback."""
    from langchain_core.messages import AIMessageChunk
    from agent.agent import ThoughtStreamFilter

    thoughts_collected = []
    tokens_collected = []

    stream_filter = ThoughtStreamFilter(
        on_token=lambda t: tokens_collected.append(t),
        on_thought=lambda t: thoughts_collected.append(t),
    )

    # Chunk with native reasoning_content (e.g. DeepSeek-R1 / Nemotron)
    stream_filter.process_chunk("", reasoning_content="Checking funding data... ")

    # Chunks with <think> tag syntax
    chunks = [
        "<th",
        "ink>Found Razorpay in DB</th",
        "ink>\nRazorpay raised $742M."
    ]
    for c in chunks:
        stream_filter.process_chunk(c)
    stream_filter.flush()

    assert "".join(thoughts_collected) == "Checking funding data... Found Razorpay in DB"
    assert "".join(tokens_collected) == "\nRazorpay raised $742M."
    assert stream_filter.get_thought() == "Checking funding data... Found Razorpay in DB"
    assert stream_filter.get_clean_content() == "Razorpay raised $742M."


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__]))


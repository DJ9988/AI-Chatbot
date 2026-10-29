"""Unit tests for the observability package (MLflow tracing, JSON audit logging, metrics)."""

import json
import sys
import tempfile
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from observability.logger import AuditLogger
from observability.metrics import MetricsCollector
from observability.tracer import flush_traces, get_last_trace_id, init_tracer


# ============================================================================
# 1. Audit Logger Tests
# ============================================================================


def test_audit_logger_write_and_read():
    """Verify structured JSON Lines writing and recent log retrieval."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "audit.jsonl"
        logger = AuditLogger(log_path=log_file)

        # Log two turns
        logger.log_turn(
            session_id="session_1",
            turn_index=1,
            user_query="What does Razorpay do?",
            bot_response="Razorpay is a payment gateway...",
            latency_ms=1200.5,
            tool_calls=[{"name": "lookup_company", "args": {"company_name": "Razorpay"}}],
            is_clarification=False,
            trace_id="tr-test-123",
        )

        logger.log_turn(
            session_id="session_1",
            turn_index=2,
            user_query="Which company is best to collaborate with?",
            bot_response="Could you clarify the domain?",
            latency_ms=450.0,
            is_clarification=True,
            trace_id="tr-test-456",
        )

        entries = logger.get_recent_logs(limit=10)
        assert len(entries) == 2

        # Verify entry 1
        e1 = entries[0]
        assert e1["session_id"] == "session_1"
        assert e1["turn_index"] == 1
        assert e1["user_query"] == "What does Razorpay do?"
        assert e1["tool_calls"][0]["name"] == "lookup_company"
        assert e1["is_clarification"] is False
        assert e1["latency_ms"] == 1200.5
        assert e1["trace_id"] == "tr-test-123"

        # Verify entry 2
        e2 = entries[1]
        assert e2["turn_index"] == 2
        assert e2["is_clarification"] is True
        assert e2["latency_ms"] == 450.0

        # Verify clear
        logger.clear()
        assert len(logger.get_recent_logs()) == 0


# ============================================================================
# 2. Metrics Collector Tests
# ============================================================================


def test_metrics_collector_aggregations():
    """Verify metric calculations for queries, clarifications, errors, tokens, and latencies."""
    collector = MetricsCollector()
    collector.reset()

    # Record 3 turns: 1 normal, 1 clarification, 1 error
    collector.record_turn(
        session_id="s1",
        latency_ms=1000.0,
        is_clarification=False,
        error=False,
        tool_names=["lookup_company"],
        token_usage={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
    )
    collector.record_turn(
        session_id="s1",
        latency_ms=2000.0,
        is_clarification=True,
        error=False,
        tool_names=[],
        token_usage={"input_tokens": 80, "output_tokens": 20, "total_tokens": 100},
    )
    collector.record_turn(
        session_id="s2",
        latency_ms=3000.0,
        is_clarification=False,
        error=True,
        is_flagged=True,
        tool_names=["filter_companies_tool"],
    )

    summary = collector.get_summary()

    assert summary["total_queries"] == 3
    assert summary["unique_sessions"] == 2
    assert summary["total_clarifications"] == 1
    assert summary["clarification_rate_pct"] == 33.33
    assert summary["total_errors"] == 1
    assert summary["error_rate_pct"] == 33.33
    assert summary["total_guardrail_flags"] == 1

    lat = summary["latency_summary"]
    assert lat["min_ms"] == 1000.0
    assert lat["max_ms"] == 3000.0
    assert lat["avg_ms"] == 2000.0
    assert lat["sample_count"] == 3

    tokens = summary["token_usage"]
    assert tokens["total_input_tokens"] == 180
    assert tokens["total_output_tokens"] == 70
    assert tokens["total_tokens"] == 250

    assert summary["tool_usage_counts"]["lookup_company"] == 1
    assert summary["tool_usage_counts"]["filter_companies_tool"] == 1


def test_metrics_export_json():
    """Verify exporting metrics summary to disk."""
    with tempfile.TemporaryDirectory() as tmpdir:
        export_file = Path(tmpdir) / "metrics.json"
        collector = MetricsCollector()
        collector.reset()

        collector.record_turn(session_id="s1", latency_ms=500.0)
        collector.export_summary(export_file)

        assert export_file.exists()
        with open(export_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert data["total_queries"] == 1
            assert data["latency_summary"]["avg_ms"] == 500.0


# ============================================================================
# 3. Tracer Tests (Langfuse)
# ============================================================================


def test_tracer_initialization():
    """Verify Langfuse tracer initialization without exceptions."""
    init_tracer()
    # Flushes without errors
    flush_traces()
    # Trace ID should be a string or None if no trace ran in this test process yet
    trace_id = get_last_trace_id()
    assert trace_id is None or isinstance(trace_id, str)


def test_langfuse_callback_handling():
    """Verify Langfuse callback handler creation in offline and configured modes."""
    from config.settings import Settings
    from observability.tracer import get_langfuse_handler, get_trace_url

    # Offline mode (when keys are empty)
    cfg = Settings(langfuse_public_key="", langfuse_secret_key="")
    assert cfg.is_langfuse_configured is False
    assert get_trace_url(settings=cfg) is None

    # Handler should return None in offline mode
    handler = get_langfuse_handler(session_id="offline_sess", settings=cfg)
    assert handler is None

    # Configured settings
    configured = Settings(
        langfuse_public_key="pk-lf-test-123",
        langfuse_secret_key="sk-lf-test-123",
        langfuse_host="http://localhost:3000",
    )
    assert configured.is_langfuse_configured is True


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__]))

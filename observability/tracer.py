"""MLflow tracing integration for LangChain and agent telemetry."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import mlflow
import mlflow.langchain

from config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

_TRACER_INITIALIZED = False


def init_tracer(settings: Optional[Settings] = None) -> None:
    """Initialize MLflow tracking and autologging for LangChain LLMs and tools."""
    global _TRACER_INITIALIZED
    if _TRACER_INITIALIZED:
        return

    # Silence agent hint log in MLflow 3.x
    os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"

    cfg = settings or get_settings()

    try:
        mlflow.set_tracking_uri(cfg.mlflow_tracking_uri)
        # Auto-restore experiment if it was previously soft-deleted
        try:
            client = mlflow.tracking.MlflowClient()
            exp = client.get_experiment_by_name(cfg.mlflow_experiment_name)
            if exp and exp.lifecycle_stage == "deleted":
                client.restore_experiment(exp.experiment_id)
        except Exception:
            pass
        mlflow.set_experiment(cfg.mlflow_experiment_name)
        # Enable LangChain autologging with inline tracer for synchronous span capture
        mlflow.langchain.autolog(run_tracer_inline=True)
        _TRACER_INITIALIZED = True
        logger.info(
            "MLflow tracing initialized: URI=%s, Experiment=%s",
            cfg.mlflow_tracking_uri,
            cfg.mlflow_experiment_name,
        )
    except Exception as exc:
        logger.warning("Could not initialize MLflow tracing: %s", exc)


def get_last_trace_id() -> Optional[str]:
    """Return the ID of the most recently recorded MLflow trace, or None."""
    try:
        return mlflow.get_last_active_trace_id()
    except Exception:
        return None


def flush_traces() -> None:
    """Flush any asynchronous trace buffers to persistent storage."""
    try:
        mlflow.flush_trace_async_logging()
    except Exception:
        pass


def get_trace_summary(trace_id: str) -> Optional[Dict[str, Any]]:
    """Fetch trace from MLflow backend and extract span hierarchy and token metrics."""
    flush_traces()
    try:
        trace = mlflow.get_trace(trace_id)
        if not trace or not getattr(trace, "data", None):
            return None

        spans_summary: List[Dict[str, Any]] = []
        total_input_tokens = 0
        total_output_tokens = 0
        detected_model: Optional[str] = None

        for span in trace.data.spans:
            duration_ms = (
                (span.end_time_ns - span.start_time_ns) / 1_000_000.0
                if (span.end_time_ns and span.start_time_ns)
                else 0.0
            )

            # Extract token usage and model if present
            attrs = span.attributes or {}
            token_usage = attrs.get("mlflow.chat.tokenUsage") or attrs.get("token_usage")
            if isinstance(token_usage, dict):
                in_tok = token_usage.get("input_tokens") or token_usage.get("prompt_tokens") or 0
                out_tok = token_usage.get("output_tokens") or token_usage.get("completion_tokens") or 0
                total_input_tokens += int(in_tok)
                total_output_tokens += int(out_tok)

            model_name = attrs.get("mlflow.llm.model") or attrs.get("model")
            if model_name and not detected_model:
                detected_model = str(model_name)

            spans_summary.append({
                "name": span.name,
                "span_type": str(span.span_type),
                "duration_ms": round(duration_ms, 2),
                "status": str(span.status.status_code) if span.status else "OK",
            })

        total_tokens = total_input_tokens + total_output_tokens

        return {
            "trace_id": trace_id,
            "experiment_id": trace.info.experiment_id if hasattr(trace, "info") else None,
            "timestamp_ms": trace.info.timestamp_ms if hasattr(trace, "info") else None,
            "spans": spans_summary,
            "span_count": len(spans_summary),
            "model": detected_model,
            "token_usage": {
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "total_tokens": total_tokens,
            },
        }
    except Exception as exc:
        logger.debug("Failed to extract trace summary for %s: %s", trace_id, exc)
        return None

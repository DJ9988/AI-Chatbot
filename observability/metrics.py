"""Metrics tracking and telemetry aggregation for the chatbot (Requirement 6)."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.settings import get_settings


class MetricsCollector:
    """In-memory and exportable metrics collector for chatbot queries and latency."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.total_queries: int = 0
        self.total_clarifications: int = 0
        self.total_errors: int = 0
        self.total_guardrail_flags: int = 0
        self.latencies_ms: List[float] = []
        self.tool_call_counts: Dict[str, int] = {}
        self.sessions_seen: set[str] = set()
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0

    def record_turn(
        self,
        session_id: str,
        latency_ms: float,
        is_clarification: bool = False,
        error: bool = False,
        is_flagged: bool = False,
        tool_names: Optional[List[str]] = None,
        token_usage: Optional[Dict[str, int]] = None,
    ) -> None:
        """Record telemetry for a single completed conversation turn."""
        with self._lock:
            self.total_queries += 1
            self.sessions_seen.add(session_id)
            self.latencies_ms.append(latency_ms)

            if is_clarification:
                self.total_clarifications += 1

            if error:
                self.total_errors += 1

            if is_flagged:
                self.total_guardrail_flags += 1

            if tool_names:
                for tool_name in tool_names:
                    self.tool_call_counts[tool_name] = (
                        self.tool_call_counts.get(tool_name, 0) + 1
                    )

            if token_usage:
                in_tok = token_usage.get("input_tokens") or token_usage.get("prompt_tokens") or 0
                out_tok = token_usage.get("output_tokens") or token_usage.get("completion_tokens") or 0
                self.total_input_tokens += int(in_tok)
                self.total_output_tokens += int(out_tok)

    def get_summary(self) -> Dict[str, Any]:
        """Compute an aggregated summary of captured metrics."""
        with self._lock:
            total = self.total_queries
            clarifications = self.total_clarifications
            errors = self.total_errors
            flags = self.total_guardrail_flags
            latencies = sorted(self.latencies_ms)

            avg_lat = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
            min_lat = round(min(latencies), 2) if latencies else 0.0
            max_lat = round(max(latencies), 2) if latencies else 0.0

            # 95th percentile latency
            if latencies:
                p95_idx = int(len(latencies) * 0.95)
                p95_lat = round(latencies[min(p95_idx, len(latencies) - 1)], 2)
            else:
                p95_lat = 0.0

            clarification_rate = round((clarifications / total) * 100, 2) if total > 0 else 0.0
            error_rate = round((errors / total) * 100, 2) if total > 0 else 0.0
            total_tokens = self.total_input_tokens + self.total_output_tokens
            avg_tokens = round(total_tokens / total, 1) if total > 0 else 0.0

            return {
                "total_queries": total,
                "unique_sessions": len(self.sessions_seen),
                "total_clarifications": clarifications,
                "clarification_rate_pct": clarification_rate,
                "total_errors": errors,
                "error_rate_pct": error_rate,
                "total_guardrail_flags": flags,
                "latency_summary": {
                    "avg_ms": avg_lat,
                    "min_ms": min_lat,
                    "max_ms": max_lat,
                    "p95_ms": p95_lat,
                    "sample_count": len(latencies),
                },
                "token_usage": {
                    "total_input_tokens": self.total_input_tokens,
                    "total_output_tokens": self.total_output_tokens,
                    "total_tokens": total_tokens,
                    "avg_tokens_per_query": avg_tokens,
                },
                "tool_usage_counts": dict(self.tool_call_counts),
            }

    def export_summary(self, export_path: Optional[Path] = None) -> Path:
        """Write metrics summary to a JSON file."""
        if export_path is None:
            settings = get_settings()
            export_path = settings.project_root / "logs" / "metrics_summary.json"
        export_path.parent.mkdir(parents=True, exist_ok=True)
        summary = self.get_summary()
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        return export_path

    def reset(self) -> None:
        """Reset all metric counters."""
        with self._lock:
            self.total_queries = 0
            self.total_clarifications = 0
            self.total_errors = 0
            self.total_guardrail_flags = 0
            self.latencies_ms.clear()
            self.tool_call_counts.clear()
            self.sessions_seen.clear()
            self.total_input_tokens = 0
            self.total_output_tokens = 0


_GLOBAL_METRICS: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """Return singleton instance of MetricsCollector."""
    global _GLOBAL_METRICS
    if _GLOBAL_METRICS is None:
        _GLOBAL_METRICS = MetricsCollector()
    return _GLOBAL_METRICS

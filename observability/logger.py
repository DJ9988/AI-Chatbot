"""Structured JSON audit logger for chatbot interactions (Requirement 5)."""

from __future__ import annotations

import datetime
import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.settings import get_settings


class AuditLogger:
    """Thread-safe JSON Lines audit logger recording queries, responses, and metrics."""

    def __init__(self, log_path: Optional[Path] = None) -> None:
        if log_path is None:
            settings = get_settings()
            log_dir = settings.project_root / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            self.log_path = log_dir / "chat_audit.jsonl"
        else:
            self.log_path = log_path
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()

    def log_turn(
        self,
        session_id: str,
        user_query: str,
        bot_response: str,
        latency_ms: float,
        turn_index: int = 1,
        sanitized_query: Optional[str] = None,
        is_safe: bool = True,
        guardrail_flags: Optional[List[str]] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        is_clarification: bool = False,
        trace_id: Optional[str] = None,
        model: Optional[str] = None,
        token_usage: Optional[Dict[str, int]] = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record a structured audit log entry for a conversation turn."""
        entry: Dict[str, Any] = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "session_id": session_id,
            "turn_index": turn_index,
            "user_query": user_query,
            "sanitized_query": sanitized_query or user_query,
            "is_safe": is_safe,
            "guardrail_flags": guardrail_flags or [],
            "tool_calls": tool_calls or [],
            "model": model,
            "token_usage": token_usage or {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "bot_response": bot_response,
            "is_clarification": is_clarification,
            "latency_ms": round(latency_ms, 2),
            "trace_id": trace_id,
            "error": error,
        }

        with self._lock:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        return entry

    def get_recent_logs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Read the most recent N log entries from the audit file."""
        if not self.log_path.exists():
            return []

        entries: List[Dict[str, Any]] = []
        with self._lock:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue

        return entries[-limit:]

    def clear(self) -> None:
        """Clear all log entries."""
        with self._lock:
            if self.log_path.exists():
                self.log_path.write_text("", encoding="utf-8")


_GLOBAL_LOGGER: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Return singleton instance of AuditLogger."""
    global _GLOBAL_LOGGER
    if _GLOBAL_LOGGER is None:
        _GLOBAL_LOGGER = AuditLogger()
    return _GLOBAL_LOGGER

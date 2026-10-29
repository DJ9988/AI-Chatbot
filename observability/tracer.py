"""Langfuse tracing integration for LangChain and agent telemetry."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

_LANGFUSE_CLIENT: Optional[Any] = None
_LAST_HANDLER: Optional[Any] = None
_IS_INITIALIZED = False


def _resolve_langfuse_host(host: str) -> str:
    """If host.docker.internal is configured but unresolvable (e.g. running on host Linux), fallback to localhost."""
    if "host.docker.internal" in host:
        try:
            import socket
            socket.gethostbyname("host.docker.internal")
        except Exception:
            return host.replace("host.docker.internal", "localhost")
    return host


def init_tracer(settings: Optional[Settings] = None) -> Optional[Any]:
    """Initialize Langfuse client if API keys are configured."""
    global _LANGFUSE_CLIENT, _IS_INITIALIZED
    if _IS_INITIALIZED:
        return _LANGFUSE_CLIENT

    cfg = settings or get_settings()

    if not cfg.is_langfuse_configured:
        logger.info(
            "Langfuse API credentials not provided; running in offline observability mode."
        )
        _IS_INITIALIZED = True
        return None

    try:
        from langfuse import Langfuse

        effective_host = _resolve_langfuse_host(cfg.langfuse_host)

        os.environ["LANGFUSE_PUBLIC_KEY"] = cfg.langfuse_public_key
        os.environ["LANGFUSE_SECRET_KEY"] = cfg.langfuse_secret_key
        os.environ["LANGFUSE_HOST"] = effective_host

        _LANGFUSE_CLIENT = Langfuse(
            public_key=cfg.langfuse_public_key,
            secret_key=cfg.langfuse_secret_key,
            host=effective_host,
        )
        _IS_INITIALIZED = True
        logger.info(
            "Langfuse tracing initialized: Host=%s",
            effective_host,
        )
        return _LANGFUSE_CLIENT
    except Exception as exc:
        logger.warning("Could not initialize Langfuse tracing: %s", exc)
        _IS_INITIALIZED = True
        return None


def get_langfuse_handler(
    session_id: Optional[str] = None,
    trace_name: Optional[str] = None,
    user_id: Optional[str] = None,
    settings: Optional[Settings] = None,
) -> Optional[Any]:
    """Return a Langfuse CallbackHandler for LangChain, or None if running offline."""
    global _LAST_HANDLER
    cfg = settings or get_settings()
    if not cfg.is_langfuse_configured:
        return None

    try:
        from langfuse.langchain import CallbackHandler

        effective_host = _resolve_langfuse_host(cfg.langfuse_host)
        os.environ["LANGFUSE_HOST"] = effective_host

        trace_context: Dict[str, Any] = {}
        if session_id:
            trace_context["session_id"] = session_id

        handler = CallbackHandler(public_key=cfg.langfuse_public_key)
        _LAST_HANDLER = handler
        return handler
    except Exception as exc:
        logger.debug("Failed creating Langfuse callback handler: %s", exc)
        return None


def flush_traces() -> None:
    """Flush any buffered Langfuse traces to the server."""
    global _LANGFUSE_CLIENT
    if _LANGFUSE_CLIENT is not None:
        try:
            _LANGFUSE_CLIENT.flush()
        except Exception as exc:
            logger.debug("Error flushing Langfuse traces: %s", exc)


def get_last_trace_id() -> Optional[str]:
    """Return the active trace ID from the last handler if available without invoking context checks."""
    global _LAST_HANDLER
    if _LAST_HANDLER is not None and getattr(_LAST_HANDLER, "last_trace_id", None):
        return str(_LAST_HANDLER.last_trace_id)
    return None


def get_trace_url(
    trace_id: Optional[str] = None, settings: Optional[Settings] = None
) -> Optional[str]:
    """Return the dashboard URL for viewing traces."""
    cfg = settings or get_settings()
    if not cfg.is_langfuse_configured:
        return None
    effective_host = _resolve_langfuse_host(cfg.langfuse_host)
    base = effective_host.rstrip("/")
    if trace_id:
        return f"{base}/project/unicorn-project/traces/{trace_id}"
    return f"{base}/project/unicorn-project/traces"

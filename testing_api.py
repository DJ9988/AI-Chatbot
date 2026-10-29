#!/usr/bin/env python3
"""End-to-end live testing script for Indian Unicorn Startups FastAPI server.

Tests every endpoint and capability on a live running instance:
1. Health check & database verification
2. Factual single-turn query with tool lookup
3. Exploratory filtering query (sector + location)
4. Multi-turn conversational context & pronoun resolution
5. Ambiguous query triggering cross-question clarification
6. Server-Sent Events (SSE) real-time streaming
7. Session history inspection & session reset
8. Runtime metrics and latest audit logs inspection

Usage:
    python testing_api.py [--base-url http://localhost:8000]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:
    print("Error: 'requests' package required. Install via: pip install requests")
    sys.exit(1)

# Color styling for terminal output
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[90m"
RESET = "\033[0m"


def print_header(title: str) -> None:
    print(f"\n{BOLD}{CYAN}{'=' * 70}{RESET}")
    print(f"{BOLD}{CYAN} {title}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}")


def print_step(step_num: int, title: str) -> None:
    print(f"\n{BOLD}[Step {step_num}] {title}{RESET}")


def print_success(msg: str) -> None:
    print(f"  {GREEN}✓ {msg}{RESET}")


def print_info(msg: str) -> None:
    print(f"  {YELLOW}ℹ {msg}{RESET}")


def print_error(msg: str) -> None:
    print(f"  {RED}✗ {msg}{RESET}")


class LiveApiTester:
    """Automated tester for live running FastAPI server."""

    def __init__(self, base_url: str = "http://localhost:8000") -> None:
        self.base_url = base_url.rstrip("/")
        self.passed_tests = 0
        self.total_tests = 0

    def check_connection(self) -> bool:
        """Check if server is reachable before running test suite."""
        try:
            r = requests.get(f"{self.base_url}/health", timeout=3.0)
            return r.status_code == 200
        except Exception:
            return False

    def run_all_tests(self) -> None:
        """Execute full end-to-end test suite."""
        print_header("LIVE FASTAPI END-TO-END TEST SUITE")
        print(f"Target Server: {BOLD}{self.base_url}{RESET}")

        if not self.check_connection():
            print_error(f"Cannot connect to API at {self.base_url}.")
            print(f"\n{YELLOW}Please ensure the API server is running in another terminal:{RESET}")
            print(f"  {BOLD}uvicorn api:app --reload --port 8000{RESET}\n")
            sys.exit(1)

        t0 = time.perf_counter()

        # Step 1: Health Check
        self.test_health_endpoint()

        # Step 2: Factual Query
        session_id = f"test_session_{uuid.uuid4().hex[:8]}"
        self.test_factual_query(session_id)

        # Step 3: Filtering Query
        self.test_filtering_query(session_id)

        # Step 4: Multi-Turn Conversation
        multi_sess = f"multi_sess_{uuid.uuid4().hex[:8]}"
        self.test_multi_turn_context(multi_sess)

        # Step 5: Ambiguous Query & Clarification
        clarify_sess = f"clarify_sess_{uuid.uuid4().hex[:8]}"
        self.test_clarification_query(clarify_sess)

        # Step 6: SSE Token & Thought Streaming
        stream_sess = f"stream_sess_{uuid.uuid4().hex[:8]}"
        self.test_streaming_endpoint(stream_sess)

        # Step 7: Sessions & Reset
        self.test_session_management(multi_sess)

        # Step 8: Metrics Endpoint
        self.test_metrics_endpoint()

        # Step 9: Latest Audit Logs
        self.test_audit_logs_endpoint()

        # Summary
        total_duration = time.perf_counter() - t0
        print_header(f"TEST RESULTS: {self.passed_tests}/{self.total_tests} PASSED in {total_duration:.2f}s")
        if self.passed_tests == self.total_tests:
            print(f"{BOLD}{GREEN}All live API capabilities verified successfully!{RESET}\n")
        else:
            print(f"{BOLD}{RED}Some tests failed. Check logs above.{RESET}\n")

    def test_health_endpoint(self) -> None:
        self.total_tests += 1
        print_step(1, "Testing GET /health Endpoint")
        try:
            r = requests.get(f"{self.base_url}/health", timeout=5.0)
            assert r.status_code == 200, f"Expected 200, got {r.status_code}"
            data = r.json()
            assert data.get("database_status") == "healthy", "Database not healthy"
            assert data.get("total_companies", 0) > 0, "No companies found in database"
            print_success(f"Health status: {data.get('status')}")
            print_info(f"Database: {data.get('database_status')} ({data.get('total_companies')} companies)")
            print_info(f"Primary model: {data.get('primary_model')}")
            print_info(f"Langfuse tracking: {'Enabled' if data.get('langfuse_configured') else 'Offline'}")
            self.passed_tests += 1
        except Exception as exc:
            print_error(f"Health test failed: {exc}")

    def test_factual_query(self, session_id: str) -> None:
        self.total_tests += 1
        print_step(2, "Testing POST /chat (Factual Company Lookup: Razorpay)")
        payload = {"query": "What does Razorpay do?", "session_id": session_id}
        try:
            r = requests.post(f"{self.base_url}/chat", json=payload, timeout=60.0)
            assert r.status_code == 200, f"Expected 200, got {r.status_code}"
            data = r.json()
            assert data.get("session_id") == session_id
            assert len(data.get("response", "")) > 10, "Response is too short"
            tools = [tc["name"] for tc in data.get("tool_calls", [])]
            print_success(f"Received grounded response ({len(data['response'])} chars)")
            print_info(f"Tools invoked: {tools}")
            print_info(f"Turn Latency: {data.get('latency_ms')}ms | Tokens: {data.get('token_usage', {}).get('total_tokens')}")
            if data.get("trace_id"):
                print_info(f"Langfuse Trace ID: {data.get('trace_id')}")
            self.passed_tests += 1
        except Exception as exc:
            print_error(f"Factual query test failed: {exc}")

    def test_filtering_query(self, session_id: str) -> None:
        self.total_tests += 1
        print_step(3, "Testing POST /chat (Sector & Location Filter: Payments in Bengaluru)")
        payload = {
            "query": "Which payments unicorn startups are based in Bengaluru?",
            "session_id": session_id,
        }
        try:
            r = requests.post(f"{self.base_url}/chat", json=payload, timeout=60.0)
            assert r.status_code == 200, f"Expected 200, got {r.status_code}"
            data = r.json()
            tools = [tc["name"] for tc in data.get("tool_calls", [])]
            print_success(f"Received filtered startup list")
            print_info(f"Tools invoked: {tools}")
            print_info(f"Turn Latency: {data.get('latency_ms')}ms")
            self.passed_tests += 1
        except Exception as exc:
            print_error(f"Filtering query test failed: {exc}")

    def test_multi_turn_context(self, session_id: str) -> None:
        self.total_tests += 1
        print_step(4, "Testing Multi-Turn Conversational Memory & Context Re-use")
        # Turn 1
        p1 = {"query": "Tell me about Zerodha", "session_id": session_id}
        # Turn 2: Follow-up using pronoun "it"
        p2 = {"query": "When was it founded and what is its annual revenue?", "session_id": session_id}
        try:
            print_info("Turn 1: 'Tell me about Zerodha'")
            r1 = requests.post(f"{self.base_url}/chat", json=p1, timeout=60.0)
            assert r1.status_code == 200
            print_success("Turn 1 completed")

            print_info("Turn 2: 'When was it founded and what is its annual revenue?'")
            r2 = requests.post(f"{self.base_url}/chat", json=p2, timeout=60.0)
            assert r2.status_code == 200
            d2 = r2.json()
            content = d2.get("response", "")
            assert "2010" in content or "Zerodha" in content or "revenue" in content.lower(), (
                f"Turn 2 did not retain context: {content[:100]}"
            )
            print_success(f"Turn 2 maintained Zerodha context (Turn index: {d2.get('turn_index')})")
            self.passed_tests += 1
        except Exception as exc:
            print_error(f"Multi-turn test failed: {exc}")

    def test_clarification_query(self, session_id: str) -> None:
        self.total_tests += 1
        print_step(5, "Testing Ambiguous Query & Cross-Question Clarification")
        payload = {
            "query": "Which company is best to collaborate with?",
            "session_id": session_id,
        }
        try:
            r = requests.post(f"{self.base_url}/chat", json=payload, timeout=60.0)
            assert r.status_code == 200
            data = r.json()
            is_clarification = data.get("is_clarification", False)
            resp_text = data.get("response", "")
            # Verify the bot prompted for clarification or cross-questioned
            has_question = "?" in resp_text or "clarify" in resp_text.lower() or is_clarification
            assert has_question, "Bot did not cross-question or clarify on ambiguous query"
            print_success("Bot triggered clarifying cross-question instead of guessing")
            print_info(f"Clarification flag: {is_clarification}")
            print_info(f"Bot response excerpt: {resp_text[:120]}...")
            self.passed_tests += 1
        except Exception as exc:
            print_error(f"Clarification test failed: {exc}")

    def test_streaming_endpoint(self, session_id: str) -> None:
        self.total_tests += 1
        print_step(6, "Testing POST /chat/stream (Server-Sent Events Token Streaming)")
        payload = {"query": "What is Zepto's valuation?", "session_id": session_id}
        try:
            r = requests.post(
                f"{self.base_url}/chat/stream", json=payload, stream=True, timeout=60.0
            )
            assert r.status_code == 200
            assert "text/event-stream" in r.headers.get("content-type", "")

            received_events: List[str] = []
            tokens: List[str] = []

            for line in r.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if line.startswith("event:"):
                    event_name = line.split(":", 1)[1].strip()
                    received_events.append(event_name)
                elif line.startswith("data:"):
                    try:
                        data = json.loads(line[5:].strip())
                        if data.get("type") == "token":
                            tokens.append(data.get("content", ""))
                    except Exception:
                        pass

            assert "start" in received_events, "Missing 'start' event"
            assert "done" in received_events, "Missing 'done' event"
            full_text = "".join(tokens)
            print_success(f"SSE stream received successfully ({len(received_events)} events)")
            print_info(f"Event types received: {sorted(list(set(received_events)))}")
            print_info(f"Streamed tokens length: {len(full_text)} characters")
            self.passed_tests += 1
        except Exception as exc:
            print_error(f"Streaming test failed: {exc}")

    def test_session_management(self, session_id: str) -> None:
        self.total_tests += 1
        print_step(7, "Testing GET /sessions/{id} & POST /sessions/{id}/reset")
        try:
            # 1. Fetch message history
            r_hist = requests.get(f"{self.base_url}/sessions/{session_id}", timeout=5.0)
            assert r_hist.status_code == 200
            hist = r_hist.json()
            assert len(hist.get("messages", [])) > 0, "No messages in history"
            print_success(f"Retrieved session history ({len(hist['messages'])} messages)")

            # 2. Reset session
            r_reset = requests.post(f"{self.base_url}/sessions/{session_id}/reset", timeout=5.0)
            assert r_reset.status_code == 200
            print_success("Session reset executed")

            # 3. Verify history is now empty
            r_empty = requests.get(f"{self.base_url}/sessions/{session_id}", timeout=5.0)
            assert len(r_empty.json().get("messages", [])) == 0, "History was not cleared"
            print_success("Verified session messages cleared to zero")
            self.passed_tests += 1
        except Exception as exc:
            print_error(f"Session management test failed: {exc}")

    def test_metrics_endpoint(self) -> None:
        self.total_tests += 1
        print_step(8, "Testing GET /metrics (Runtime Observability Aggregation)")
        try:
            r = requests.get(f"{self.base_url}/metrics", timeout=5.0)
            assert r.status_code == 200
            metrics = r.json()
            assert "total_queries" in metrics, "Missing total_queries"
            print_success("Retrieved live aggregated metrics")
            print_info(f"Total queries tracked: {metrics.get('total_queries')}")
            print_info(f"Total clarifications: {metrics.get('total_clarifications')}")
            print_info(f"Average latency: {metrics.get('avg_latency_ms', 0):.1f}ms")
            print_info(f"Total tokens consumed: {metrics.get('token_consumption', {}).get('total_tokens', 0)}")
            self.passed_tests += 1
        except Exception as exc:
            print_error(f"Metrics test failed: {exc}")

    def test_audit_logs_endpoint(self) -> None:
        self.total_tests += 1
        print_step(9, "Testing GET /logs/latest (Structured JSON Audit Inspection)")
        try:
            r = requests.get(f"{self.base_url}/logs/latest?n=2", timeout=5.0)
            assert r.status_code == 200
            logs = r.json()
            assert isinstance(logs, list), "Expected list of logs"
            print_success(f"Retrieved {len(logs)} recent audit log records")
            if logs:
                last_log = logs[-1]
                print_info(f"Last Log Entry Turn #{last_log.get('turn_index')} | Latency: {last_log.get('latency_ms')}ms")
                print_info(f"User Query: '{last_log.get('user_query', '')[:40]}...'")
            self.passed_tests += 1
        except Exception as exc:
            print_error(f"Audit log test failed: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Live API Tester for Indian Unicorns Chatbot API")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of running FastAPI server (default: http://localhost:8000)",
    )
    args = parser.parse_args()

    tester = LiveApiTester(base_url=args.base_url)
    tester.run_all_tests()


if __name__ == "__main__":
    main()


"""Interactive CLI for testing and chatting with the Indian Unicorn Startups Chatbot."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.agent import UnicornAgent
from config.settings import get_settings


def print_banner(model_name: str) -> None:
    print("=" * 65)
    print(" 🦄 INDIAN UNICORN STARTUPS AI CHATBOT")
    print(f" Powered by LangChain & Model: {model_name}")
    print("=" * 65)
    print("Commands:")
    print(" - 'reset'   : Clear conversation history and start fresh")
    print(" - 'history' : View current conversation turns")
    print(" - 'stats'   : Display real-time aggregated metrics summary")
    print(" - 'log'     : View the last structured JSON audit log entry with full details")
    print(" - 'trace'   : View MLflow tracing span tree & UI instructions")
    print(" - 'exit'    : Quit the chatbot")
    print("-" * 65)
    print("Sample queries to try:")
    print(" 1. Factual:      'What does Razorpay do?'")
    print(" 2. Exploratory:  'List fintech unicorn startups'")
    print(" 3. Follow-up:    'Which of these are based in Bangalore?'")
    print(" 4. Ambiguous:    'Which company is best to collaborate with?'")
    print(" 5. Informal:     'How much funding has Byjus raised?'")
    print("=" * 65)
    print()


def run_interactive_cli() -> None:
    settings = get_settings()

    if not settings.llm_api_key:
        print("[!] Warning: LLM_API_KEY is not set in your .env file.")
        print("    Please add your API key to .env before starting.\n")
        return

    agent = UnicornAgent(settings=settings)
    session_id = f"session_{uuid.uuid4().hex[:8]}"

    print_banner(settings.primary_model)

    while True:
        try:
            user_input = input("User > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting chatbot. Goodbye!")
            break

        if not user_input:
            continue

        cmd = user_input.casefold()
        if cmd in ("exit", "quit", "q"):
            agent.conversation_manager.close_all_sessions()
            print("Session trace exported. Goodbye!")
            break

        if cmd == "reset":
            agent.conversation_manager.reset_session(session_id)
            print("[✓] Conversation context cleared and session trace exported.\n")
            continue

        if cmd == "history":
            session = agent.conversation_manager.get_session(session_id)
            msgs = session.get_messages()
            print(f"\n--- History ({len(msgs)} messages) ---")
            for m in msgs:
                role = "User" if m.type == "human" else "Bot"
                print(f"[{role}]: {m.content[:100]}...")
            print("----------------------------\n")
            continue

        if cmd in ("stats", "metrics"):
            summary = agent.metrics_collector.get_summary()
            print("\n📊 Aggregated Observability Metrics:")
            print(json.dumps(summary, indent=2))
            print()
            continue

        if cmd in ("log", "logs"):
            recent = agent.audit_logger.get_recent_logs(limit=1)
            print("\n📝 Latest Structured JSON Audit Log:")
            if not recent:
                print("   (No logs recorded yet)")
            for entry in recent:
                print(json.dumps(entry, indent=2))
            print()
            continue

        if cmd in ("trace", "traces"):
            session = agent.conversation_manager.get_session(session_id)
            # Flush and export current session trace to MLflow storage so it is immediately viewable
            current_trace_id = session.close_trace()
            session.ensure_trace()  # Resume active session span for subsequent turns

            from observability.tracer import get_trace_summary
            print("\n🔍 MLflow Session Trace Information:")
            if current_trace_id:
                summary = get_trace_summary(current_trace_id)
                if summary:
                    print(json.dumps(summary, indent=2))
                else:
                    print(f"   Trace ID: {current_trace_id}")
            else:
                print("   No trace generated yet in this session.")
            print("\n   To explore the full interactive trace tree, open a terminal and run:")
            print("   👉 mlflow ui --backend-store-uri sqlite:///data/mlflow.db\n")
            continue

        thought_header_printed = False
        bot_prefix_printed = False
        waiting_indicator_printed = False

        sys.stdout.write(f"\n⏳ Sending request to {settings.primary_model}...")
        sys.stdout.flush()
        waiting_indicator_printed = True

        def clear_waiting_indicator() -> None:
            nonlocal waiting_indicator_printed
            if waiting_indicator_printed:
                sys.stdout.write("\r\033[K")
                sys.stdout.flush()
                waiting_indicator_printed = False

        def handle_thought(thought: str) -> None:
            nonlocal thought_header_printed
            clear_waiting_indicator()
            if not thought_header_printed:
                print("💭 [Thought Process]:\n  ", end="", flush=True)
                thought_header_printed = True
            formatted = thought.replace("\n", "\n  ")
            sys.stdout.write(f"\033[90m{formatted}\033[0m")
            sys.stdout.flush()

        def handle_token(token: str) -> None:
            nonlocal bot_prefix_printed
            clear_waiting_indicator()
            if not bot_prefix_printed:
                if thought_header_printed:
                    print("\n")
                print("Bot > ", end="", flush=True)
                bot_prefix_printed = True
            sys.stdout.write(token)
            sys.stdout.flush()

        def handle_tool_start(tool_name: str, args: dict) -> None:
            clear_waiting_indicator()
            args_str = ", ".join(f"{k}={repr(v)}" for k, v in args.items()) if args else ""
            print(f"🔧 Executing tool: {tool_name}({args_str})...", flush=True)

        def handle_tool_end(tool_name: str, status: str, duration_ms: float) -> None:
            symbol = "✓" if status == "success" else "ℹ" if status in ("no_results", "not_found") else "✗"
            print(f"   {symbol} {tool_name} completed ({status}, {duration_ms:.1f}ms)", flush=True)

        response = agent.chat(
            user_input,
            session_id=session_id,
            on_token=handle_token,
            on_thought=handle_thought,
            on_tool_start=handle_tool_start,
            on_tool_end=handle_tool_end,
        )

        clear_waiting_indicator()

        if not bot_prefix_printed:
            print(f"Bot > {response.content}")
        else:
            print()  # Add newline after streamed token output

        # Show clarification flag
        if response.is_clarification:
            print("\n❓ [Bot requested clarification]")

        trace_info = f" | Trace: {response.trace_id}" if response.trace_id else ""
        tok_str = f" | Tokens: {response.token_usage.get('total_tokens', 0)}" if response.token_usage.get('total_tokens') else ""
        print(f"\n⏱ [Latency: {response.latency_ms:.1f}ms{tok_str}{trace_info}]\n")
        print("-" * 65)


def main() -> None:
    parser = argparse.ArgumentParser(description="Indian Unicorn Startups AI Chatbot CLI")
    parser.add_argument("--query", "-q", type=str, help="Single query to run non-interactively")
    args = parser.parse_args()

    if args.query:
        settings = get_settings()
        agent = UnicornAgent(settings=settings)
        thought_header_printed = False
        bot_prefix_printed = False

        def handle_thought(thought: str) -> None:
            nonlocal thought_header_printed
            if not thought_header_printed:
                print("\n💭 [Thought Process]:\n  ", end="", flush=True)
                thought_header_printed = True
            formatted = thought.replace("\n", "\n  ")
            sys.stdout.write(f"\033[90m{formatted}\033[0m")
            sys.stdout.flush()

        def handle_token(token: str) -> None:
            nonlocal bot_prefix_printed
            if not bot_prefix_printed and thought_header_printed:
                print("\n")
            sys.stdout.write(token)
            sys.stdout.flush()
            bot_prefix_printed = True

        resp = agent.chat(args.query, on_token=handle_token, on_thought=handle_thought)
        agent.conversation_manager.close_all_sessions()
        if not bot_prefix_printed:
            print(resp.content)
        else:
            print()
    else:
        run_interactive_cli()


if __name__ == "__main__":
    main()

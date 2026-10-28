"""Interactive CLI for testing and chatting with the Indian Unicorn Startups Chatbot."""

from __future__ import annotations

import argparse
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
    print(" - 'reset' : Clear conversation history and start fresh")
    print(" - 'history': View current conversation turns")
    print(" - 'exit'   : Quit the chatbot")
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
            print("Goodbye!")
            break

        if cmd == "reset":
            agent.conversation_manager.reset_session(session_id)
            print("[✓] Conversation context cleared.\n")
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

        print("\n[Thinking...]")
        response = agent.chat(user_input, session_id=session_id)

        # Show executed tools (if any)
        if response.tool_calls:
            print("\n🔧 Tools Executed:")
            for call in response.tool_calls:
                print(f"   • {call['name']}({call['args']})")

        # Show clarification flag
        if response.is_clarification:
            print("\n❓ [Bot requested clarification]")

        print(f"\nBot > {response.content}")
        print(f"\n⏱ [Latency: {response.latency_ms:.1f}ms]\n")
        print("-" * 65)


def main() -> None:
    parser = argparse.ArgumentParser(description="Indian Unicorn Startups AI Chatbot CLI")
    parser.add_argument("--query", "-q", type=str, help="Single query to run non-interactively")
    args = parser.parse_args()

    if args.query:
        settings = get_settings()
        agent = UnicornAgent(settings=settings)
        resp = agent.chat(args.query)
        print(resp.content)
    else:
        run_interactive_cli()


if __name__ == "__main__":
    main()


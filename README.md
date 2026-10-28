# Indian Unicorn Startups AI Chatbot

A production-grade Python AI chatbot that answers questions about 118 Indian unicorn startups strictly from a static dataset using **LangChain**, **SQLite (with FTS5 Full-Text Search)**, and **MLflow Tracing**.

Built to satisfy all requirements of the AI Engineer Coding Assignment:
- **Strict dataset grounding**: Relies solely on static dataset facts; handles missing data gracefully without hallucinating.
- **Dynamic retrieval (zero hardcoded dictionaries)**: Purely data-driven tools for lookup, filtering, full-text search, and schema introspection.
- **Multi-turn conversation context**: Retains conversation history across queries.
- **Real-time token & thought streaming**: Live token-by-token output streaming, tool execution status reporting, and transparent reasoning/thinking token capture (`reasoning_content` and `<think>` scratchpads).
- **Cross-questioning & clarification**: Asks clarifying questions for ambiguous or underspecified queries instead of guessing.
- **Security & query sanitization**: Unicode normalization, control character stripping, length capping, and prompt injection detection.
- **Comprehensive observability**: End-to-end MLflow Tracing (`AGENT`, `GUARDRAIL`, `TOOL`, `RETRIEVER`, `CHAT_MODEL` spans), structured JSON audit logging (`logs/chat_audit.jsonl`), and latency/token telemetry metrics.

---

## 🏗 High-Level Architecture

```mermaid
flowchart TD
    User["User / CLI"] --> Sanitizer["Security Sanitizer (GUARDRAIL Span)"]
    Sanitizer --> Agent["Unicorn Agent (AGENT Root Span)"]
    Agent --> History["Session State & Trimming (Multi-Turn Context)"]
    Agent --> LLM1["ChatOpenAI (meta/llama-3.2-11b)"]
    LLM1 -->|Tool Proposal| ToolDispatch["Tool Dispatcher"]
    
    ToolDispatch --> DBTools["Dynamic Tools (tools/db_tools.py)"]
    DBTools -->|lookup_company| SQLite["SQLite Database (companies)"]
    DBTools -->|filter_companies| SQLite
    DBTools -->|search_companies| FTS5["SQLite FTS5 (companies_fts)"]
    DBTools -->|get_available_filters| SQLite
    
    DBTools -->|Retrieved Records (RETRIEVER Span)| LLM2["ChatOpenAI (Synthesis)"]
    LLM2 --> Response["Grounded Answer / Clarification"]
    
    Agent --> AuditLog["Audit Logger (logs/chat_audit.jsonl)"]
    Agent --> Metrics["Metrics Collector (logs/metrics_summary.json)"]
    Agent --> MLflowStore["MLflow DB (sqlite:///data/mlflow.db)"]
```

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.10+ (tested on Python 3.11 - 3.14)
- Git

### 2. Environment Setup

```bash
# Create and activate virtual environment
python -m venv myenv
source myenv/bin/activate       # On Linux/macOS
# or: myenv\Scripts\activate   # On Windows

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure `.env`

Copy the sample environment file and configure your API keys:

```bash
cp .env.example .env
```

Edit `.env`:
```ini
# Kaggle API token (required only once to download raw dataset)
KAGGLE_API_KEY="your-kaggle-api-key"

# OpenAI-Compatible Provider (e.g., NVIDIA NIM, OpenAI, vLLM, Ollama)
LLM_BASE_URL="https://integrate.api.nvidia.com/v1"
LLM_API_KEY="your-api-key"
PRIMARY_MODEL="meta/llama-3.2-11b-vision-instruct"
FALLBACK_MODELS="meta/llama-3.2-90b-vision-instruct"
LLM_TEMPERATURE=0.2
LLM_TIMEOUT=45.0
LLM_MAX_RETRIES=1

# Observability (MLflow SQLite backend stored in data/)
MLFLOW_TRACKING_URI="sqlite:///data/mlflow.db"
MLFLOW_EXPERIMENT_NAME="indian_unicorns_chatbot"
```

### 4. Build Dataset & SQLite Database

```bash
python data/create_dataset.py
```
This script downloads the Kaggle dataset (if missing), normalizes missing values and text anomalies, and generates:
- `data/processed/companies.db`: SQLite database with indexes on `primary_sector`, `location`, and a `companies_fts` FTS5 index.
- `data/processed/tracxn.csv`: Normalized CSV data.

---

## 💻 Running the Chatbot

### Interactive CLI

```bash
python cli.py
```

Inside the CLI, you can chat naturally or use the built-in commands:
- `stats`   : View real-time aggregated metrics (queries, clarifications, errors, tokens, latencies).
- `log`     : Inspect the full structured JSON audit record of the last interaction.
- `trace`   : View MLflow trace spans and command instructions.
- `history` : View multi-turn conversation messages.
- `reset`   : Clear session context and start fresh.
- `exit`    : Quit the CLI.

### Non-Interactive Single Query

```bash
python cli.py --query "What does Razorpay do?"
```

---

## 📊 Viewing Observability & Traces in MLflow UI

To inspect interactive trace trees, span durations, token consumption, and input/output payloads:

```bash
mlflow ui --backend-store-uri sqlite:///data/mlflow.db
```

Open your browser at **http://localhost:5000** and select the `indian_unicorns_chatbot` experiment.

### What is captured in each MLflow Trace:
- **`Session: <session_id>` (AGENT root span)**: Holds the entire multi-turn conversation session in a single unified trace tree, capturing the complete message history across turns (`user` and `assistant` messages).
- **`Turn <N>: <query>` (CHAIN span)**: Each conversation turn within the session, capturing the user query, turn index, latency, and response.
- **`query_sanitizer` (GUARDRAIL span)**: Unicode normalization, control character removal, length cap, prompt injection heuristics.
- **`RunnableWithFallbacks` (CHAIN span)**: LangChain invocation with automated provider fallback routing.
- **`ChatOpenAI` (CHAT_MODEL span)**: Full prompt messages, completion text, latency, token usage (`input_tokens`, `output_tokens`, `total_tokens`).
- **`lookup_company` / `filter_companies_tool` / `search_companies_tool` (TOOL span)**: Exact arguments, execution duration, and returned data.

### Structured Audit Logging (`logs/chat_audit.jsonl`)
Every turn writes an audit entry formatted as:
```json
{
  "timestamp": "2026-10-28T09:19:48.064244+00:00",
  "session_id": "live_obs_demo",
  "turn_index": 1,
  "user_query": "What does Razorpay do?",
  "sanitized_query": "What does Razorpay do?",
  "is_safe": true,
  "guardrail_flags": [],
  "tool_calls": [
    {
      "name": "lookup_company",
      "args": { "company_name": "Razorpay" },
      "duration_ms": 3.86,
      "status": "success"
    }
  ],
  "model": "meta/llama-3.2-11b-vision-instruct",
  "token_usage": { "input_tokens": 3080, "output_tokens": 121, "total_tokens": 3201 },
  "bot_response": "Razorpay is a provider of online payment gateway solutions for businesses...",
  "is_clarification": false,
  "latency_ms": 14285.57,
  "trace_id": "tr-ae689408023dff4b6b3e9f58baec5d45",
  "error": null
}
```

---

## 🧪 Running Tests

The test suite contains **87 comprehensive unit tests** covering data normalization, tools, agent lifecycle, real-time streaming, thought routing, observability, and sanitization:

```bash
pytest -v
```

Test breakdown:
- `tests/test_create_dataset.py`: 35 tests for pipeline, schemas, text normalization, SQLite table creation, and missing value handling.
- `tests/test_tools.py`: 28 tests for company lookups (exact, case-insensitive, fuzzy, punctuation-insensitive), parameterized filtering, FTS5 escaping, and SQL injection safety.
- `tests/test_agent.py`: 9 tests for ReAct tool loop, multi-turn history trimming, clarification detection, real-time token/tool streaming, and live thought stream routing.
- `tests/test_config.py`: 5 tests for provider-agnostic `.env` settings and LangChain `.with_fallbacks()`.
- `tests/test_agent.py`: 7 tests for multi-turn history trimming, clarification detection, tool calling, and session isolation.
- `tests/test_observability.py`: 4 tests for JSONL audit writing/reading, metrics computation (percentiles, rates, tokens), and trace initialization.
- `tests/test_sanitizer.py`: 5 tests for unicode normalization, length capping, and prompt injection detection.

---

## 💡 Sample Interactions

> 📘 **Looking for a comprehensive evaluation test suite?**  
> Check out [TEST_QUERIES.md](file:///home/wolfie/ai_chatbot/TEST_QUERIES.md) for 25+ curated test cases spanning factual lookups, multi-turn follow-ups, context re-use, full-text capability search, typo tolerance, ambiguity handling, and security injection tests.

### 1. Factual Company Query
```text
User > What does Razorpay do?
🔧 Tools Executed:
   • lookup_company({'company_name': 'Razorpay'})
Bot > Razorpay is a provider of online payment gateway solutions for businesses. It offers payment solutions, automated payroll, in-person payments, and banking services for businesses. It allows businesses to accept, process, and disburse payments through various methods, including credit cards, debit cards, net banking, UPI, and digital wallets.
⏱ [Latency: 7847.1ms | Tokens: 3270 | Trace: tr-b1ab8af06d6166d7b10373a1f8d5214d]
```

### 2. Handling Missing Metrics (Grounding)
```text
User > How much funding has Byjus raised?
🔧 Tools Executed:
   • lookup_company({'company_name': 'Byjus'})
Bot > Unfortunately, the total funding till date for Byju's is not recorded in the dataset. However, I can provide you with some other relevant financial metrics that are available:
* Valuation: $4.45B
* Annual Revenue: $120M as of June 4, 2024
* Latest Funding Round: Conventional Debt, May 12, 2023, $250M
⏱ [Latency: 3409.6ms | Tokens: 3223 | Trace: tr-f14c23e6164a453b5b91dcd2231a6cd7]
```

### 3. Ambiguous / Underspecified Query (Cross-Questioning)
```text
User > Which company is best to collaborate with?
❓ [Bot requested clarification]
Bot > Which company would be best to collaborate with depends on your specific goals and industry. Could you clarify what type of collaboration you are looking for (e.g., payment infrastructure, logistics, enterprise SaaS, or marketing)?
⏱ [Latency: 2157.1ms | Tokens: 1424 | Trace: tr-a9d151b335734fe19b2ff9514b32ee3a]
```

### 4. Multi-Turn Follow-Up Query
```text
User > List fintech unicorn startups
🔧 Tools Executed:
   • filter_companies_tool({'sector': 'Payments, Banking Tech, Alternative Lending'})
Bot > Here are notable fintech unicorns from the dataset:
* Razorpay (Payments, Bengaluru, Valuation: $7.5B)
* CRED (Payments, Bengaluru, Valuation: $6.4B)
* Pine Labs (Payments, Noida, Valuation: $5.0B)
* Groww (Investment Tech, Bengaluru, Valuation: $3.0B)

User > Which of these are based in Bangalore?
🔧 Tools Executed:
   • filter_companies_tool({'sector': 'Payments, Banking Tech, Alternative Lending', 'location': 'Bengaluru'})
Bot > From the fintech unicorns listed, the following are based in Bengaluru:
* Razorpay
* CRED
* Groww
* Juspay
* Money View
```

---

## 📁 Repository Structure

```text
ai_chatbot/
├── config/
│   ├── settings.py           # Pydantic environment configuration & defaults
│   └── provider.py           # Provider-agnostic ChatOpenAI factory with fallbacks
├── data/
│   ├── create_dataset.py     # Download, normalize, and build SQLite + FTS5 database
│   ├── raw/                  # Downloaded raw CSV (created by create_dataset.py)
│   ├── processed/            # companies.db and normalized tracxn.csv
│   └── mlflow.db             # SQLite backend store for MLflow traces
├── tools/
│   ├── __init__.py
│   └── db_tools.py           # Dynamic SQLite retrieval tools (zero hardcoded dictionaries)
├── agent/
│   ├── prompts.py            # System prompt with grounding & clarification rules
│   ├── state.py              # ConversationManager and SessionState message history
│   └── agent.py              # UnicornAgent orchestrating ReAct loop & observability
├── security/
│   ├── __init__.py
│   └── sanitizer.py          # Input normalization, length capping, prompt injection checks
├── observability/
│   ├── tracer.py             # MLflow tracing initialization and span inspection
│   ├── logger.py             # Structured JSON Lines audit logger (logs/chat_audit.jsonl)
│   └── metrics.py            # MetricsCollector tracking queries, clarifications, latency, tokens
├── logs/
│   ├── chat_audit.jsonl      # Machine-readable structured interaction log
│   └── metrics_summary.json  # Exported metrics summary
├── tests/
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_create_dataset.py
│   ├── test_tools.py
│   ├── test_agent.py
│   ├── test_observability.py
│   └── test_sanitizer.py
├── cli.py                    # Interactive command-line interface
├── requirements.txt
├── .env.example
└── README.md
```

---

## 📌 Assumptions & Limitations

1. **Static Dataset Snapshot**:
   - The knowledge base is strictly limited to the static 118 unicorn startups in the provided Kaggle dataset (snapshot through May 2024 / 2025). Facts reflect only what is in the dataset.
2. **Missing Field Transparency**:
   - Total funding till date is unrecorded for several companies in the source dataset. The bot explicitly informs the user that this specific metric is missing while presenting alternative financial facts (valuation, annual revenue, stage).
3. **Hardware / Network Independence**:
   - The application relies on standard OpenAI HTTP spec and can be pointed to any provider (`LLM_BASE_URL`) such as NVIDIA NIM, OpenAI, Anthropic via proxy, vLLM, or Ollama locally without modifying chatbot code.

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
    Agent --> LangfuseStore["Langfuse Tracing (Self-Hosted Docker / Langfuse Cloud)"]
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

# Observability (Langfuse Tracing - Self-Hosted Docker or Langfuse Cloud)
LANGFUSE_PUBLIC_KEY="pk-lf-..."
LANGFUSE_SECRET_KEY="sk-lf-..."
LANGFUSE_HOST="http://localhost:3000"
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
- `reset`   : Clear session context and start fresh with a clean conversation turn.
- `exit`    : Quit the CLI.

### Non-Interactive Single Query

```bash
python cli.py --query "What does Razorpay do?"
```

### 🌐 Running the FastAPI REST & Streaming Server

To run the production REST API with automatic interactive OpenAPI / Swagger docs:

```bash
uvicorn api:app --reload --port 8000
```

Open your browser at:
- **Interactive Swagger Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc Documentation:** [http://localhost:8000/redoc](http://localhost:8000/redoc)

#### Key Endpoints:
- `POST /chat`: Synchronous conversation turn with full latency, tool calls, and Langfuse trace metadata.
- `POST /chat/stream`: Real-time Server-Sent Events (SSE) token and thought streaming.
- `GET /health`: System and SQLite database connectivity check.
- `GET /sessions`: List active in-memory conversation sessions.
- `GET /sessions/{session_id}`: Inspect multi-turn message history for a session.
- `POST /sessions/{session_id}/reset`: Clear session context and flush traces.
- `GET /metrics`: Aggregated queries, clarifications, and latency summary.
- `GET /logs/latest?n=5`: Retrieve recent structured audit log records.

#### Live API Functional Verification:

With `uvicorn api:app` running in one terminal, run the automated live test suite in another:

```bash
python testing_api.py
```
This tests all 9 live capabilities sequentially (Health, Factual lookup, Multi-parameter filter, Multi-turn memory, Clarifying cross-questions, SSE streaming, Session history & reset, Metrics, and JSON audit logs) with formatted terminal output.

---

## 🐳 Docker Deployment

The project separates the **Chatbot Application** container from the **Observability Stack** for production-grade modularity:

### 1. Deploy the Chatbot Application Container

A production-ready [`Dockerfile`](file:///home/wolfie/ai_chatbot/Dockerfile) and [`docker-compose.yml`](file:///home/wolfie/ai_chatbot/docker-compose.yml) build and run the chatbot API:

```bash
# Build and run the chatbot API container
docker compose up -d --build
```

- **API URL:** [http://localhost:8000](http://localhost:8000)
- **Interactive Swagger Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **Persistent Volume:** Host `./logs/` mapped to container `/app/logs`

### 2. Run Local Langfuse Observability Stack (Optional)

The full Langfuse stack with ClickHouse, PostgreSQL, Redis, MinIO, and auto-provisioned credentials is located in `deploy/`:

```bash
# Start local Langfuse stack
sudo docker compose -f deploy/docker-compose.langfuse.yml up -d

# Open UI: http://localhost:3000
# Login: admin@local.host / adminpassword123
```

*(To stop the observability stack: `sudo docker compose -f deploy/docker-compose.langfuse.yml down`)*

### 3. Container-to-Host Observability Networking
- **Langfuse Cloud (Default/Production):** Set `LANGFUSE_HOST=https://cloud.langfuse.com` in `.env`.
- **Local Langfuse in Docker:** When running the chatbot inside its container while Langfuse is on the host, set:
  ```ini
  LANGFUSE_HOST="http://host.docker.internal:3000"
  ```
  *(The root `docker-compose.yml` automatically includes `extra_hosts: ["host.docker.internal:host-gateway"]` to route seamlessly).*

---

## 📊 Observability & Traces with Langfuse

The chatbot natively integrates with **Langfuse** for production GenAI tracing, multi-turn thread observability, and LLM call analytics.

### Option A: Local Self-Hosted Langfuse via Docker (Recommended for Local Dev)

A complete, automated `docker-compose.yml` with OTLP trace ingestion is included:

```bash
# 1. Start the local Langfuse stack (ClickHouse, Postgres, Redis, MinIO, Worker, Web)
sudo docker compose up -d

# 2. Access the dashboard:
# URL: http://localhost:3000
# Email: admin@local.host
# Password: adminpassword123

# 3. Configure your .env:
LANGFUSE_PUBLIC_KEY="pk-lf-local-unicorns"
LANGFUSE_SECRET_KEY="sk-lf-local-unicorns"
LANGFUSE_HOST="http://localhost:3000"
```

To stop the containers:
```bash
sudo docker compose down
```

### Option B: Langfuse Cloud

If you prefer managed cloud tracing:
1. Sign up at [cloud.langfuse.com](https://cloud.langfuse.com) (or EU cloud: [cloud.langfuse.com](https://cloud.langfuse.com)).
2. Generate API keys from project settings.
3. Add keys to `.env`:
   ```ini
   LANGFUSE_PUBLIC_KEY="pk-lf-..."
   LANGFUSE_SECRET_KEY="sk-lf-..."
   LANGFUSE_HOST="https://cloud.langfuse.com"
   ```

*(Note: If Langfuse keys are omitted, the chatbot operates gracefully in offline no-op mode with local structured JSON audit logging).*

### What is captured in each Langfuse Trace:
- **`Session / Thread ID` (`session_id`)**: Groups all turns of a conversation under a single session view.
- **`Turn <N>: <query>`**: Individual trace per turn tracking latency, user query, and final answer.
- **`ChatOpenAI`**: Model parameters, token usage counts (`input_tokens`, `output_tokens`, `total_tokens`), raw prompt, and raw model output.
- **`Dynamic Tools` (`lookup_company`, `filter_companies_tool`, `search_companies_tool`)**: Tool inputs, return payloads, and execution latency.
- **`ThoughtStreamFilter` / Reasoning**: Extracted thinking content and reasoning tags.

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

The test suite contains **95 comprehensive unit tests** covering data normalization, tools, agent lifecycle, real-time streaming, thought routing, FastAPI endpoints, observability, and sanitization:

```bash
pytest -v
```

Test breakdown:
- `tests/test_create_dataset.py`: 35 tests for pipeline, schemas, text normalization, SQLite table creation, and missing value handling.
- `tests/test_tools.py`: 28 tests for company lookups (exact, case-insensitive, fuzzy, punctuation-insensitive), parameterized filtering, FTS5 escaping, and SQL injection safety.
- `tests/test_agent.py`: 10 tests for ReAct tool loop, multi-turn history trimming, clarification detection, real-time token/tool streaming, and live thought stream routing.
- `tests/test_api.py`: 7 tests verifying FastAPI endpoints (`/health`, `/chat`, `/chat/stream`, `/sessions`, `/metrics`, `/logs/latest`).
- `tests/test_config.py`: 6 tests for provider-agnostic `.env` settings, alias properties, and LangChain `.with_fallbacks()`.
- `tests/test_observability.py`: 4 tests for JSONL audit writing/reading, metrics computation (percentiles, rates, tokens), and trace initialization.
- `tests/test_sanitizer.py`: 5 tests for unicode normalization, length capping, and prompt injection detection.

---

## 📋 Live Model Capabilities Showcase ([TEST_QUERIES.md](TEST_QUERIES.md))

For an extensive live demonstration of the chatbot's real-world capabilities, refer to [**TEST_QUERIES.md**](TEST_QUERIES.md). It documents exact model responses, tool executions, and latency metrics across all 8 functional evaluation categories:

| Category | Capability Evaluated | Highlights & Demonstrated Live Behavior |
|---|---|---|
| **1. Factual Company Lookups** | Single-entity retrieval, metric extraction | Precise lookups for Razorpay, Zepto, Zerodha, and overseas-headquartered Postman with zero hallucinations. |
| **2. Exploratory & Filtering Queries** | Parametric multi-condition filtering | Autonomous schema discovery (`fintech` → payments, lending, banking tech), year ranges, and complete 56 sector listings. |
| **3. Free-Text Semantic Search (FTS)** | Unstructured company background search | FTS5 BM25 search across EV mobility (Ather, Ola Electric), logistics (Delhivery, XpressBees), and gaming (Hike, MPL, Dream11). |
| **4. Conversational Memory & Context Re-use** | Multi-turn state, anaphora resolution | Zero-tool follow-ups ("Which of these are based in Bangalore?", "Where is it headquartered?"), sub-second memory retrieval, Zerodha vs Groww comparison. |
| **5. Ambiguity & Cross-Questioning** | Subjective intent clarification | Proactive cross-questioning for broad advice ("Which company is best to collaborate with?"), disambiguating "most successful". |
| **6. Typo Tolerance & Fuzzy Matching** | Levenshtein distance & phonetic matching | Auto-corrects `Razorypay` → Razorpay, normalizes `Byjus` → BYJU'S, resolves substring `1mg` → Tata 1mg. |
| **7. Out-of-Dataset & Missing Fields** | Strict knowledge grounding | Refuses to hallucinate for non-dataset companies (Stripe, OpenAI); transparently reports bootstrapped status for Zerodha. |
| **8. Security & Input Sanitization** | Prompt injection & SQL injection defense | Blocks jailbreak attempts in **33.8ms**, neutralizes SQL injection (`DROP TABLE`), and strips control characters safely. |

👉 **Read the full showcase with exact prompts, tool payloads, and outputs in [TEST_QUERIES.md](TEST_QUERIES.md).**

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
│   └── processed/            # companies.db and normalized tracxn.csv
├── Dockerfile                # Production Dockerfile for chatbot FastAPI application
├── docker-compose.yml        # Application deployment compose (FastAPI service)
├── deploy/
│   └── docker-compose.langfuse.yml  # Local Langfuse production observability stack
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
│   ├── tracer.py             # Langfuse tracing client & LangChain CallbackHandler
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
│   ├── test_api.py
│   ├── test_observability.py
│   └── test_sanitizer.py
├── cli.py                    # Interactive command-line interface
├── api.py                    # FastAPI REST & SSE streaming server
├── testing_api.py            # End-to-end live API functional verification script
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

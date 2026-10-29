# Indian Unicorn Startups AI Chatbot

A production-grade, grounded conversational AI assistant that answers questions about 118 Indian unicorn startups strictly from a structured dataset using **LangChain**, **FastAPI**, **SQLite (with FTS5 Full-Text Search)**, and **Langfuse Tracing**.

---

## 🌟 Key Highlights

- **Strict Dataset Grounding**: Zero hallucinations. Relies strictly on SQLite data; transparently communicates unrecorded metrics and handles out-of-dataset entities gracefully.
- **Dynamic Retrieval**: 100% data-driven tools with zero hardcoded company or sector mappings.
- **Conversational Memory**: Retains multi-turn conversation context, resolves pronouns and anaphora, and avoids redundant database queries.
- **Real-Time Streaming**: Server-Sent Events (SSE) token-by-token streaming with live reasoning/thought token capture.
- **Clarification Triggers**: Automatically cross-questions users on subjective, ambiguous, or underspecified queries.
- **Security & Sanitization**: Guardrails against prompt injection, SQL injection neutralization, length capping, and Unicode normalization.
- **Production Observability**: Full trace capture with Langfuse, structured append-only JSON audit logs, and runtime telemetry metrics endpoints.

---

## 🏗 System Architecture

```mermaid
flowchart TD
    User["User / Client (CLI, REST, SSE)"] --> Sanitizer["Security Sanitizer (Prompt & SQL Injection Checks)"]
    Sanitizer --> Agent["Unicorn Agent (ReAct Controller)"]
    Agent --> State["Session State & Memory (Sliding Window History)"]
    Agent --> LLM["LLM via LangChain (ChatOpenAI Provider-Agnostic)"]
    
    LLM -->|Tool Proposal| Dispatcher["Dynamic Tool Dispatcher"]
    Dispatcher -->|lookup_company| DB["SQLite (companies)"]
    Dispatcher -->|filter_companies| DB
    Dispatcher -->|search_companies| FTS["SQLite FTS5 (BM25 Search)"]
    Dispatcher -->|get_available_filters| DB
    
    DB --> Dispatcher
    FTS --> Dispatcher
    Dispatcher -->|Grounded Evidence| LLM
    LLM --> Response["Streaming / Final Answer"]
    
    Agent --> Audit["Structured JSON Audit Log (logs/chat_audit.jsonl)"]
    Agent --> Metrics["Runtime Metrics Collector (data/metrics.json)"]
    Agent --> Langfuse["Langfuse Tracing (Host or Cloud)"]
```

---

## 📌 Assumptions & Limitations

1. **Static Dataset Snapshot**:
   - The knowledge base is strictly limited to the static 118 unicorn startups in the provided Kaggle dataset. Facts reflect only what is recorded in the dataset.
2. **Missing Field Transparency**:
   - Total funding till date and certain valuations are unrecorded/null for several companies in the source dataset. The bot explicitly informs the user that these metrics are missing while reporting all available alternatives (annual revenue, latest round, stage).
3. **Provider-Agnostic LLM Interface**:
   - The application conforms to standard OpenAI-compatible HTTP specs. It can target any provider (`LLM_BASE_URL`) such as Mistral, OpenAI, NVIDIA NIM, vLLM, or Ollama locally without code changes.
4. **Observability Routing**:
   - The chatbot currently routes traces to a local Langfuse stack (which can be started via `deploy/docker-compose.langfuse.yml`). To deploy remotely, simply update `LANGFUSE_HOST` in `.env` to point to [Langfuse Cloud](https://cloud.langfuse.com) or your hosted instance. If omitted, the chatbot operates gracefully in offline mode.

---

## 📋 Live Model Capabilities Showcase ([TEST_QUERIES.md](TEST_QUERIES.md))

For an end-to-end evaluation log of the chatbot's live behavior, refer to [**TEST_QUERIES.md**](TEST_QUERIES.md). 

It documents verified model responses, dynamic tool invocations, and execution telemetry across 8 core evaluation categories:
- **Factual Company Lookups**: Single-entity retrieval for domestic and overseas-relocated unicorns (Razorpay, Zepto, Zerodha, Postman) with zero hallucinations.
- **Exploratory & Parametric Filtering**: Structured queries across sectors, cities, and founded years with autonomous schema discovery and fallback.
- **Free-Text Semantic Search (FTS)**: SQLite FTS5 BM25 search across unstructured company offerings (EVs, logistics, gaming).
- **Conversational Memory & Context Re-use**: Multi-turn dialogue, pronoun resolution, and sub-second follow-up answers without redundant database calls.
- **Ambiguity & Cross-Questioning**: Proactive clarification triggers for broad or subjective user inquiries before searching.
- **Typo Tolerance & Fuzzy Matching**: Automatic correction of company names, punctuation normalization, and substring matching.
- **Grounding & Missing Fields**: Transparent reporting of unrecorded metrics (bootstrapped status, null valuations) and graceful out-of-dataset entity handling.
- **Security & Guardrails**: Sub-50ms prompt injection interception, SQL injection neutralization, and control character sanitization.

---

## 🚀 Quickstart

### 1. Installation

```bash
# Clone repository and navigate to folder
cd ai_chatbot

# Create and activate virtual environment
python3 -m venv myenv
source myenv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Environment Configuration

Copy the template and fill in your keys:
```bash
cp .env.example .env
```

Configure `.env`:
```ini
# Kaggle API token (required only once to download the raw dataset)
KAGGLE_API_KEY="your-kaggle-api-key"

# LLM Provider (OpenAI, Mistral, NVIDIA NIM, vLLM, Ollama, etc.)
LLM_BASE_URL="https://api.mistral.ai/v1"
LLM_API_KEY="your-api-key"
PRIMARY_MODEL="open-mistral-nemo"
FALLBACK_MODELS="mistral-small-latest"
LLM_TEMPERATURE=0.2
LLM_TIMEOUT=30.0

# Observability (Self-Hosted Local Docker or Langfuse Cloud)
LANGFUSE_PUBLIC_KEY="pk-lf-local-unicorns"
LANGFUSE_SECRET_KEY="sk-lf-local-unicorns"
LANGFUSE_HOST="http://localhost:3000"
```

### 3. Build Database

Requires `KAGGLE_API_KEY` set in `.env` to download the raw data:
```bash
python data/create_dataset.py
```
This downloads, cleans, and builds the SQLite database (`data/processed/companies.db`).

---

## 💻 Usage & Interfaces

### 1. Interactive Terminal CLI
```bash
python cli.py
```
- Type natural questions directly in the terminal.
- Commands: `reset` (clear conversation history), `exit` (quit).

### 2. FastAPI REST & Streaming Server
```bash
uvicorn api:app --reload --port 8000
```
- **Interactive Swagger Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc Documentation**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

#### Core Endpoints:
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/chat` | Synchronous conversation turn with latency, tool payloads, and Langfuse trace metadata |
| `POST` | `/chat/stream` | Server-Sent Events (SSE) token and reasoning token streaming |
| `GET` | `/health` | Service and SQLite database connectivity status |
| `GET` | `/sessions` | List active in-memory conversation sessions |
| `GET` | `/sessions/{id}` | Retrieve conversation turn history for a session |
| `POST` | `/sessions/{id}/reset` | Reset a session's conversational memory |
| `GET` | `/metrics` | Real-time aggregated latency, token counts, and tool metrics |
| `GET` | `/logs/latest?n=5` | Structured JSON audit trail inspection |

### 3. End-to-End Live API Test Suite
Verify all 9 capabilities against the running server in one command:
```bash
python testing_api.py
```

---

## 🐳 Docker Deployment

The deployment separates the **application service** from the **observability stack** for maximum modularity:

### Application Container
Deploy the containerized FastAPI chatbot:
```bash
docker compose up -d --build
```
- Chatbot API: [http://localhost:8000](http://localhost:8000)
- Auto-configured to route local traces to `host.docker.internal:3000`.

### Local Langfuse Stack (Optional)
Run the self-hosted Langfuse stack (ClickHouse, Postgres, Redis, MinIO, Web UI):
```bash
docker compose -f deploy/docker-compose.langfuse.yml up -d
```
- Web UI: [http://localhost:3000](http://localhost:3000) (Default login: `admin@local.host` / `adminpassword123`)

---

## 🧪 Automated Testing

Run the full offline test suite (95 tests):
```bash
pytest -v
```

| Suite | Tests | Scope |
|---|---|---|
| `tests/test_create_dataset.py` | 35 | Kaggle download, text cleaning, SQLite creation, missing value masks |
| `tests/test_tools.py` | 28 | Exact lookups, fuzzy matching, parameterized filters, SQL injection safety |
| `tests/test_agent.py` | 10 | ReAct loop, history trimming, clarification detection, streaming tokens |
| `tests/test_api.py` | 7 | REST endpoints, SSE token streaming, session reset, health checks |
| `tests/test_config.py` | 6 | Settings validation, fallback models, provider setup |
| `tests/test_sanitizer.py` | 5 | Unicode normalization, length truncation, prompt injection filters |
| `tests/test_observability.py` | 4 | JSONL audit logs, metrics computation, Langfuse handler dispatch |

---

## 📁 Project Structure

```text
ai_chatbot/
├── config/                  # Settings and provider-agnostic ChatOpenAI factory
│   ├── settings.py
│   └── provider.py
├── data/                    # Dataset extraction, cleaning, and SQLite database
│   ├── create_dataset.py
│   └── processed/
│       ├── companies.db     # SQLite database with FTS5 search table
│       └── tracxn.csv       # Cleaned dataset CSV
├── agent/                   # Agent core, system prompts, and conversational memory
│   ├── agent.py
│   ├── prompts.py
│   └── state.py
├── tools/                   # Dynamic database tools (lookup, filter, FTS, schema)
│   └── db_tools.py
├── security/                # Sanitization and prompt injection guardrails
│   └── sanitizer.py
├── observability/           # Langfuse tracing, JSON audit logging, and metrics
│   ├── tracer.py
│   ├── logger.py
│   └── metrics.py
├── deploy/                  # Production Docker Compose for local Langfuse
│   └── docker-compose.langfuse.yml
├── tests/                   # 95 unit and integration tests
├── Dockerfile               # Production container definition for FastAPI app
├── docker-compose.yml       # Application deployment compose file
├── api.py                   # FastAPI REST and SSE streaming server
├── cli.py                   # Interactive terminal chat interface
├── testing_api.py           # Live end-to-end API test script
├── TEST_QUERIES.md          # Live model performance and capability showcase
├── requirements.txt         # Production dependencies
└── README.md                # Project documentation
```

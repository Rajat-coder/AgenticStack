# ⚡ AgenticTask

An AI-powered development assistant that turns JIRA tickets into GitHub Pull Requests — automatically.

Assign a ticket, review the plan, click Approve. The agent reads your codebase, writes the code, and raises the PR.

---

## What It Does

1. **Reads your JIRA ticket** — title, description, acceptance criteria
2. **Analyzes your codebase** — using AgenticStack.txt for context
3. **Generates a plan** — which files to change, what steps to take, risk level
4. **Waits for your approval** — no code is written until you say so
5. **Writes the code** — on a feature branch, never touches main
6. **Raises a GitHub PR** — with auto-generated description linked to the ticket
7. **Gets smarter over time** — learns from approved/rejected jobs via fine-tuning

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18 + Vite |
| Backend | FastAPI (Python, async) |
| Database | PostgreSQL + pgvector |
| ORM | SQLAlchemy (async) |
| Real-time | WebSocket |
| LLM | Anthropic Claude / OpenAI GPT-4o |
| Vector Search | pgvector (hybrid: semantic + keyword + RRF) |
| Fine-Tuning | OpenAI Fine-Tuning API |
| JIRA | REST API |
| GitHub | REST API |

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│              React Dashboard                     │
│  Tickets · Jobs · Plan Approval · Fine-Tuning   │
└────────────────────┬────────────────────────────┘
                     │ REST + WebSocket
┌────────────────────▼────────────────────────────┐
│              FastAPI Backend                     │
│                                                 │
│  Agent Harness (state machine + crash recovery) │
│  Context Engineer (token-aware RAG)             │
│  Planner LLM  →  Executor LLM  →  PR Raiser    │
│  Vector Search (pgvector hybrid + RRF)          │
│  Fine-Tuning Engine (JSONL + OpenAI API)        │
└────────────────────┬────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
      JIRA        GitHub      PostgreSQL
      API          API        + pgvector
```

---

## Project Structure

```
agentictask/
├── backend/
│   ├── main.py                  # FastAPI app, CORS, lifespan
│   ├── config.py                # All env vars (pydantic-settings)
│   ├── deps.py                  # Singleton harness (prevents circular imports)
│   ├── ws.py                    # WebSocket connection manager
│   ├── agent/
│   │   ├── harness.py           # State machine, crash recovery, watchdog, retries
│   │   ├── orchestrator.py      # plan_job → execute_code → raise_pr
│   │   ├── planner.py           # LLM call → structured plan JSON
│   │   ├── executor.py          # LLM call → writes code, commits to branch
│   │   ├── context.py           # Context engineer — builds focused context package
│   │   ├── search.py            # pgvector hybrid search (vector + keyword + RRF)
│   │   └── finetuning.py        # Training data collection + fine-tune job submission
│   ├── integrations/
│   │   ├── jira.py              # JIRA REST API wrapper
│   │   └── github.py            # GitHub REST API wrapper
│   ├── api/
│   │   ├── agent.py             # assign, approve, revise, stop, list jobs
│   │   ├── tickets.py           # list JIRA tickets
│   │   ├── settings.py          # read/update prompt configs
│   │   ├── finetuning.py        # label examples, export, start fine-tune
│   │   └── ws.py                # WebSocket endpoint
│   └── db/
│       ├── models.py            # Job, EventLog, PromptConfig, TrainingExample, JobEmbedding
│       └── session.py           # Async DB engine + session factory + seed prompts
├── frontend/
│   └── src/
│       ├── App.jsx              # Shell + WebSocket connection + tab routing
│       ├── App.css              # Dark theme design system
│       └── components/
│           ├── Dashboard.jsx    # Tickets + Jobs two-pane layout
│           ├── AgentPanel.jsx   # Plan display + approve/revise/stop
│           ├── StatusBadge.jsx  # Real-time color-coded status chip
│           ├── Settings.jsx     # Prompt editor + model parameter sliders
│           └── FineTuning.jsx   # Label jobs + export + trigger fine-tuning
├── .env.example
└── docker-compose.yml
```

---

## Job Lifecycle

```
QUEUED
  → GATHERING_CONTEXT   (reads JIRA + codebase + similar past jobs)
  → PLANNING            (LLM generates plan)
  → AWAITING_APPROVAL   (waits for human — no code written yet)
  → EXECUTING           (LLM writes code, commits to feature branch)
  → RAISING_PR          (opens GitHub PR, updates JIRA to "In Review")
  → COMPLETED

Any state → FAILED | TIMED_OUT
```

---

## Key Concepts Built From Scratch

| Concept | Where |
|---|---|
| Agent Harness (state machine + crash recovery) | `agent/harness.py` |
| Context-aware RAG | `agent/context.py` |
| Hybrid vector search (pgvector + tsvector + RRF) | `agent/search.py` |
| IVFFlat index for fast approximate nearest-neighbour | pgvector |
| Fine-tuning pipeline (JSONL export + OpenAI API) | `agent/finetuning.py` |
| Plan revision loop | `agent/orchestrator.py` |
| Real-time WebSocket status updates | `ws.py` + `api/ws.py` |
| Prompt versioning (never overwrites, full history) | `api/settings.py` |
| Exponential backoff on LLM retries | `agent/harness.py` |
| Token budget management | `agent/context.py` |

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/agentictask.git
cd agentictask

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Start PostgreSQL

```bash
docker compose up -d db
```

### 3. Enable pgvector

```sql
-- Run in psql or pgAdmin
CREATE EXTENSION IF NOT EXISTS vector;
```

### 4. Configure environment

```bash
cp .env.example .env
# Fill in your keys
```

### 5. Start backend

```bash
uvicorn backend.main:app --reload
# API: http://localhost:8000
# Docs: http://localhost:8000/docs
```

### 6. Start frontend

```bash
cd frontend
npm install
npm run dev
# Dashboard: http://localhost:3000
```

---

## Environment Variables

```env
# AI — at least one required
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
AI_PROVIDER=anthropic          # anthropic | openai | ollama

# JIRA
JIRA_BASE_URL=https://yourcompany.atlassian.net
JIRA_EMAIL=you@company.com
JIRA_API_TOKEN=
JIRA_PROJECT_KEY=

# GitHub
GITHUB_TOKEN=
GITHUB_REPO_OWNER=
GITHUB_REPO_NAME=

# Target repo (where agent writes code)
TARGET_REPO_PATH=

# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/agentictask

# Ollama (optional — local LLM)
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=codellama:7b-instruct
```

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/agent/assign` | Assign JIRA ticket to agent |
| POST | `/agent/approve/{job_id}` | Approve the generated plan |
| POST | `/agent/revise/{job_id}` | Give feedback to revise plan |
| POST | `/agent/stop/{job_id}` | Stop a running job |
| GET | `/agent/jobs` | List all jobs |
| GET | `/agent/jobs/{job_id}` | Get one job with plan |
| GET | `/tickets` | List JIRA tickets |
| GET | `/settings/prompt/{step}` | Get active prompt config |
| PUT | `/settings/prompt/{step}` | Update prompt (creates new version) |
| POST | `/finetuning/approve/{job_id}` | Mark job as approved training example |
| POST | `/finetuning/reject/{job_id}` | Mark job as rejected with reason |
| POST | `/finetuning/export` | Export training data as JSONL |
| POST | `/finetuning/start` | Submit fine-tuning job to OpenAI |
| WS | `/ws` | Real-time job status updates |

Full interactive docs at `http://localhost:8000/docs`

---

## Fine-Tuning Flow

```
1. Agent completes job → PR raised on GitHub
2. You review the PR code
3. Dashboard → Fine-Tuning tab → Approve or Reject with reason
4. After 10+ approved examples → Export JSONL → Start Fine-Tuning
5. OpenAI trains custom model → returns fine-tuned model ID
6. Agent now uses your custom model — knows your codebase patterns
```

---

Built as a learning project covering: agent harness architecture, RAG, vector search, hybrid search, fine-tuning, WebSocket, state machines, and LLM integration.

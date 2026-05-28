# AgenticTask — Project Context & Learning Guide

## What We Are Building

AgenticTask is an agentic development assistant that connects JIRA, GitHub,
and your codebase context to automate software development tasks on your behalf.

A developer sees their assigned JIRA tickets in a React dashboard, assigns a
ticket to the AI agent, and the agent — using full codebase context — plans the
work, writes the code, waits for approval, then raises a GitHub PR automatically.

**What makes this project special for learning:**
This single project covers harness architecture, fine-tuning, prompt engineering,
vector databases, real-time systems, state machines, and LLM integration —
exactly what the market is hiring for in 2025–2026.

---

## Project Roadmap — 0 to 100

### The Big Picture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        AGENTICTASK — FULL MAP                           │
├──────────────┬──────────────────────────────────────────────────────────┤
│  PHASE 1     │  Foundation: FastAPI + PostgreSQL + Harness              │
│  PHASE 2     │  Integrations: JIRA MCP + GitHub MCP + Context Engineer  │
│  PHASE 3     │  Agent Brain: LLM calls + Planner + Executor + PR Raiser │
│  PHASE 4     │  API Layer: REST endpoints + WebSocket real-time          │
│  PHASE 5     │  Fine-Tuning Engine: JSONL + training data + ML tuning   │
│  PHASE 6     │  Vector Search: pgvector + Hybrid + Hierarchical         │
│  PHASE 7     │  React Frontend: Dashboard + Agent Panel + Settings      │
└──────────────┴──────────────────────────────────────────────────────────┘
```

---

### PHASE 1 — Foundation
**What we build:** The skeleton everything else runs on.

```
backend/
├── main.py          ← FastAPI app, CORS, lifespan startup
├── config.py        ← All env vars loaded via pydantic-settings
├── db/
│   ├── models.py    ← Job, EventLog, PromptConfig, TrainingExample tables
│   └── session.py   ← Async PostgreSQL connection + session factory
└── agent/
    └── harness.py   ← State machine + crash recovery + watchdog + retries
```

**Concepts covered in Phase 1:**

| Concept | How it appears in THIS project |
|---|---|
| **FastAPI** | `main.py` — async app, router registration, lifespan startup hook |
| **Pydantic** | `config.py` — env vars validated as typed Python objects, not raw strings |
| **SQLAlchemy (async)** | `db/session.py` — `AsyncSession`, `create_async_engine`, connection pool |
| **PostgreSQL** | One DB for all environments. Migrations via Alembic. |
| **ORM Models** | `db/models.py` — Python classes map 1:1 to DB tables |
| **State Machine** | `harness.py` — `JobStatus` enum, `transition()` method that validates moves |
| **Crash Recovery** | `harness.py` — on startup, query DB for EXECUTING/PLANNING jobs → resume them |
| **Timeout Watchdog** | `harness.py` — `asyncio.wait_for()` wraps each step. Exceeded → `TIMED_OUT` |
| **Exponential Backoff** | `harness.py` — `asyncio.sleep(2**attempt)` before retrying failed LLM calls |
| **Async/Await** | Everywhere — FastAPI, SQLAlchemy, harness steps all use `async def` |
| **WebSocket (setup)** | `main.py` — WebSocket connection manager registered at startup |

**What you can explain after Phase 1:**
- Why async matters for AI backends
- What a state machine is and why the harness uses one
- How crash recovery works (read DB state on restart)
- What exponential backoff is and when to use it
- Difference between SQLAlchemy model and a DB table

---

### PHASE 2 — Integrations + Context Engineer
**What we build:** Everything the agent reads before thinking.

```
backend/
├── integrations/
│   ├── jira.py      ← JIRA MCP wrapper — read ticket, update status
│   └── github.py    ← GitHub MCP wrapper — check branches, open PRs
└── agent/
    └── context.py   ← Context engineer — builds focused context package
```

**Concepts covered in Phase 2:**

| Concept | How it appears in THIS project |
|---|---|
| **MCP (Model Context Protocol)** | `jira.py` + `github.py` — agent calls JIRA/GitHub as structured tool calls via MCP, not custom HTTP code |
| **Tool Use / Function Calling** | Agent receives a list of available MCP tools and decides which to call — same pattern as LLM function calling |
| **RAG (basic)** | `context.py` — reads AgenticStack.txt, extracts only sections matching ticket keywords |
| **Token Counting** | `context.py` — `tiktoken` library counts tokens before sending to LLM. Filters if over limit. |
| **Context Window Management** | `context.py` — relevance scoring to decide which sections to keep when context is too large |
| **agenticstackfile** | PyPI package — generates structured codebase map via AST analysis |

**What MCP actually is (explained simply):**
```
Without MCP:                          With MCP:
jira_api.get_ticket(id)               agent.call_tool("jira_get_ticket", {"id": id})
github_api.create_pr(...)             agent.call_tool("github_create_pr", {...})
↑ every integration is custom code    ↑ every tool is called the same way
```
MCP is to AI agents what HTTP is to web browsers — a standard protocol so any
agent can talk to any tool without custom integration code.

**What you can explain after Phase 2:**
- What MCP is and why it exists
- What RAG is and how the context engineer implements it
- What a context window is and how to manage token budgets
- What tool use / function calling means

---

### PHASE 3 — Agent Brain (LLM Calls)
**What we build:** The actual AI — planner, executor, PR raiser.

```
backend/agent/
├── orchestrator.py  ← Receives context, runs planner→executor→PR raiser in sequence
├── planner.py       ← LLM call that produces a written plan for user approval
└── executor.py      ← LLM call that writes code + commits to branch
```

**Concepts covered in Phase 3:**

| Concept | How it appears in THIS project |
|---|---|
| **LLM API (Anthropic)** | `orchestrator.py` — `anthropic.Anthropic().messages.create(...)` |
| **LLM API (OpenAI)** | `orchestrator.py` — `openai.OpenAI().chat.completions.create(...)` |
| **System Prompt** | `planner.py` — loaded from DB (`PromptConfig` table), injected as `role: system` |
| **Temperature** | `orchestrator.py` — `0.6` for planner, `0.1` for executor. Loaded from DB per step. |
| **Max Tokens** | `orchestrator.py` — `2048` for plan, `4096` for code. Prevents runaway output. |
| **Top-P** | `orchestrator.py` — nucleus sampling, configurable per step |
| **Structured Output** | `planner.py` — prompt instructs LLM to return JSON. Parsed and validated with Pydantic. |
| **Prompt Engineering** | Per-step system prompts, custom rules injection, `.agentictask.md` per-repo overrides |
| **Fine-Tuning Layer 1** | System prompt stored in DB, editable from dashboard, versioned |
| **Fine-Tuning Layer 2** | Temperature/max_tokens stored in DB per step, editable without restart |
| **Few-Shot Prompting** | `orchestrator.py` — similar past jobs (from Phase 6) injected as examples |

**Why we are NOT using LangChain:**
LangChain is a framework that wraps all of the above into chains and agents.
It is widely used in production, but it hides the internals.

By building Phase 3 from scratch you will understand exactly what LangChain does
under the hood. After this phase, if someone shows you LangChain code you will
immediately recognise every concept — because you built the same thing manually.

LangChain equivalent of what we build here:
```
Our code                    LangChain equivalent
─────────────────────────── ──────────────────────────────
orchestrator.py             LLMChain / AgentExecutor
planner.py                  PromptTemplate + LLM + OutputParser
executor.py                 Tool + AgentAction
context package             Document + VectorStoreRetriever (Phase 6)
```

**What you can explain after Phase 3:**
- How to call Anthropic and OpenAI APIs directly
- What temperature, top-p, max_tokens actually do
- What structured output / JSON mode is
- What prompt engineering is and how system prompts work
- What LangChain does (because you built it yourself first)

---

### PHASE 4 — API Layer + WebSocket
**What we build:** The control surface that replaces manual test scripts with real HTTP endpoints.
Before Phase 4, the only way to assign a ticket was to run `test_run.py` in the shell.
After Phase 4, any client — browser, curl, React dashboard — can control the agent via REST API.

```
backend/
├── ws.py              ← ConnectionManager class + connection_manager singleton
│                         Moved out of main.py to prevent circular imports
├── deps.py            ← harness singleton (AgentHarness instance)
│                         Both main.py and api/agent.py import from here — not from each other
└── api/
    ├── ws.py          ← WebSocket endpoint router (/ws)
    ├── tickets.py     ← GET /tickets, GET /tickets/{id}
    ├── agent.py       ← POST /agent/assign
    │                     POST /agent/approve/{job_id}
    │                     POST /agent/stop/{job_id}
    │                     GET  /agent/jobs
    │                     GET  /agent/jobs/{job_id}
    └── settings.py    ← GET /settings/prompt/{step}
                          PUT /settings/prompt/{step}
```

Also added `get_project_tickets()` to `integrations/jira.py` — uses JIRA's JQL search API
to fetch all tickets in the project (needed by GET /tickets).

---

**Concepts covered in Phase 4:**

| Concept | How it appears in THIS project |
|---|---|
| **APIRouter** | Each file creates its own `router = APIRouter(prefix=...)`. `main.py` mounts all of them with `app.include_router()`. Routes stay grouped by concern. `main.py` stays clean. |
| **BackgroundTasks** | `POST /agent/assign` returns 201 in milliseconds. Harness runs AFTER the response is sent. Without this, the browser would hang for minutes waiting for the agent to finish. |
| **Depends(get_db)** | FastAPI injects a DB session into every route that declares `db: AsyncSession = Depends(get_db)`. Same session, same transaction, auto-committed on success, rolled back on error. |
| **Pydantic request models** | `AssignRequest`, `UpdatePromptRequest` — FastAPI validates incoming JSON automatically. Wrong field type or missing required field → 422 response, not a Python crash. |
| **Pydantic response models** | `JobResponse`, `TicketResponse`, `PromptResponse` — document exactly what the API returns. API contract is separate from internal domain models. |
| **HTTPException** | `raise HTTPException(status_code=404, detail="Job not found")` → FastAPI sends a proper JSON error. Never return raw strings for errors. |
| **HTTP status codes** | 200 OK (success), 201 Created (new resource), 404 Not Found, 409 Conflict (duplicate job or wrong state), 422 Unprocessable Entity (bad request body) |
| **Singleton pattern** | `connection_manager` and `harness` are module-level singletons. Created once at import time. Shared across all requests. |
| **Circular import prevention** | `api/agent.py` needs `harness`. `main.py` needs `harness`. If `agent.py` imported from `main.py` and `main.py` imported from `agent.py` → circular import crash. Solution: both import `harness` from `deps.py` instead. |
| **Approve flow ordering** | `transition(AWAITING_APPROVAL → EXECUTING)` commits to DB FIRST. Then `harness.run_job()` is added to background. If reversed: harness reads `AWAITING_APPROVAL`, treats it as a WAITING_STATE, skips the job entirely. |
| **WebSocket vs REST** | REST = browser asks, server answers, connection closes. WebSocket = persistent connection, server pushes whenever state changes. REST is used for commands (assign, approve, stop). WebSocket is used for live status (browser never has to poll). |
| **Prompt version history** | `PUT /settings/prompt/{step}` does NOT overwrite. It deactivates all old versions and creates a new one with `version + 1`. Full history preserved. Roll back any time by reactivating an old version. |
| **Swagger auto-docs** | FastAPI generates `/docs` automatically from route definitions. Every endpoint, request body, and response model is documented and callable from the browser. No extra work needed. |
| **CORS** | `main.py` allows `http://localhost:3000` (React frontend) to call `http://localhost:8000` (backend). Without CORS, browsers block cross-origin requests entirely. |

---

**The full job lifecycle through the API — step by step:**

Step 1 — Browser calls `POST /agent/assign` with `{ticket_id, ticket_title}`
Step 2 — FastAPI creates a Job row in DB (status = QUEUED), returns 201 in milliseconds
Step 3 — BackgroundTasks runs `harness.run_job()` after the response is sent
Step 4 — Harness: QUEUED → GATHERING_CONTEXT → PLANNING → AWAITING_APPROVAL
Step 5 — Each transition calls `broadcast()` → WebSocket pushes to browser instantly
Step 6 — Harness stops at AWAITING_APPROVAL. Waits for human.

Step 7 — Browser calls `GET /agent/jobs/{job_id}` → sees the plan (summary, files, steps)
Step 8 — User reads plan, clicks Approve
Step 9 — Browser calls `POST /agent/approve/{job_id}`
Step 10 — FastAPI transitions job to EXECUTING and commits to DB
Step 11 — BackgroundTasks runs `harness.run_job()` — harness sees EXECUTING, runs execute_code()
Step 12 — Harness: EXECUTING → RAISING_PR → COMPLETED
Step 13 — Each transition broadcasts over WebSocket → browser badge updates in real time

The browser makes exactly 3 HTTP calls for the whole flow.
Everything else — all status updates — arrive via WebSocket push.

---

**Why the approve endpoint transitions BEFORE starting the background task:**

```python
# CORRECT — transition first, then background
await harness.transition(db, job, JobStatus.EXECUTING, "Approved")  # saved to DB
background_tasks.add_task(harness.run_job, job.id)                  # harness reads EXECUTING ✓

# WRONG — background first, then transition
background_tasks.add_task(harness.run_job, job.id)   # harness reads AWAITING_APPROVAL
await harness.transition(...)                         # too late — harness already skipped it
```

The harness checks status from DB. AWAITING_APPROVAL is a WAITING_STATE — harness skips it.
You must write EXECUTING to DB first, then let the harness read it.

---

**Why singletons need their own module (the circular import problem):**

```
PROBLEM:
  main.py     creates harness, imports api/agent.py
  api/agent.py needs harness, imports main.py
  → Python sees: main.py imports agent.py imports main.py → crash

SOLUTION:
  deps.py     creates harness (imports nothing from api/ or main.py)
  main.py     imports harness from deps.py ✓
  api/agent.py imports harness from deps.py ✓
  Neither imports from the other. No cycle.
```

Same pattern for ConnectionManager — lives in `ws.py`, imported by both `main.py` and `api/ws.py`.

---

**What you can explain after Phase 4:**
- How to design a REST API — resources, verbs, status codes, when to use each
- Why WebSocket exists and when to use it instead of REST (commands vs live updates)
- What dependency injection is and how FastAPI's `Depends()` works
- What BackgroundTasks does and why it's essential for long-running agent jobs
- How Pydantic validates requests and responses automatically
- What CORS is and why browsers enforce it
- How circular imports happen and how to solve them with a singleton module
- Why the approve flow must transition DB state before starting the background task
- How prompt versioning works (deactivate old, create new — never delete)
- What Swagger /docs is and how FastAPI generates it automatically

---

### PHASE 5 — Fine-Tuning Engine
**What we build:** The system that makes the agent smarter over time.

```
backend/agent/
└── finetuning.py     ← Training data collection, JSONL export, fine-tune job submission

backend/api/
└── finetuning.py     ← POST /finetuning/export, POST /finetuning/start, GET /finetuning/status
```

**Concepts covered in Phase 5:**

| Concept | How it appears in THIS project |
|---|---|
| **Fine-Tuning (ML)** | Upload JSONL to OpenAI/Anthropic → they retrain model weights → return custom model ID |
| **JSONL Format** | `finetuning.py` — export approved jobs as one JSON object per line |
| **Training Data Pipeline** | Every approved job → stored as `TrainingExample` → exported → submitted |
| **Model Versioning** | Fine-tuned model IDs stored in DB with version numbers. Old versions kept for rollback. |
| **Feedback Loop** | Approved jobs = positive examples. Rejected = stored for analysis. Model improves with use. |
| **Polling Pattern** | `finetuning.py` — after submitting job, poll provider API every 60s until `succeeded` |

**The fine-tuning feedback loop:**
```
User assigns ticket → agent produces plan → user APPROVES
                                                   ↓
                               TrainingExample saved to DB
                                                   ↓
                        (after 10+ examples) User triggers fine-tune
                                                   ↓
                              JSONL exported → submitted to OpenAI
                                                   ↓
                       Provider trains → returns fine-tuned model ID
                                                   ↓
                    Agent now uses your custom model for this codebase
```

**What you can explain after Phase 5:**
- What fine-tuning is vs prompt engineering (different layers)
- What JSONL is and why it's the standard format
- How the training feedback loop works
- What a fine-tuned model ID is and how to use it

---

### PHASE 6 — Vector Search (High-Accuracy Semantic Search)
**What we build:** Semantic memory — finding past similar jobs to use as examples.

```
backend/
├── db/models.py          ← Add chunk_embeddings + sentence_embeddings tables
└── agent/
    └── search.py         ← Hierarchical search + hybrid fusion + contextual embeddings
```

**Concepts covered in Phase 6:**

| Concept | How it appears in THIS project |
|---|---|
| **pgvector** | PostgreSQL extension — `vector(1536)` column type, `<=>` cosine distance operator |
| **Embeddings** | `search.py` — call `openai.embeddings.create()` to convert text → vector |
| **Hierarchical Indexing** | Index sentences AND their parent chunks. Search sentences, return chunks. |
| **Hybrid Search** | pgvector cosine similarity + PostgreSQL `tsvector` keyword search, combined via RRF |
| **RRF (Reciprocal Rank Fusion)** | `search.py` — merge two ranked lists into one without normalising scores |
| **Contextual Embeddings** | Prepend document summary to each sentence before embedding — improves recall |
| **IVFFlat Index** | `CREATE INDEX ... USING ivfflat` — fast approximate nearest-neighbour search |
| **Few-Shot Prompting** | Top-3 similar past jobs injected into agent context as examples |
| **Semantic vs Keyword Search** | "user can't sign in" finds "authentication error" — meaning, not words |

**Why this beats standard RAG:**
```
Standard RAG:         Split into 500-token chunks → embed chunk → search chunk
                      Problem: relevant sentence buried in noisy chunk

This project:         Split into sentences → embed sentence → search sentence
                      On match: fetch parent chunk → send chunk to LLM
                      Result: precision of sentence search + context of chunk retrieval

Plus keyword layer:   "AuthenticationError" class → no semantic neighbours
                      PostgreSQL full-text search finds it via exact match
                      RRF fuses both results → single ranked list
```

**What you can explain after Phase 6:**
- What a vector database is and how it works
- What embeddings are (numbers that represent meaning)
- Why standard chunking fails and how hierarchical indexing fixes it
- What hybrid search is and what RRF does
- What pgvector is vs ChromaDB vs Pinecone (and when to use each)
- What few-shot prompting is

---

### PHASE 7 — React Frontend
**What we build:** The dashboard the developer uses.

```
frontend/src/components/
├── Dashboard.jsx          ← Ticket board, list of all assigned tickets
├── TicketCard.jsx         ← Single ticket — title, status badge, assign button
├── AgentPanel.jsx         ← Plan display, approve button, live status stream
├── StatusBadge.jsx        ← Real-time colour-coded status indicator
└── Settings/
    ├── PromptEditor.jsx   ← Edit system prompts, custom rules
    ├── ModelParams.jsx    ← Sliders for temperature, max_tokens, top_p
    └── FineTuning.jsx     ← Training example count, trigger fine-tune button
```

**Concepts covered in Phase 7:**

| Concept | How it appears in THIS project |
|---|---|
| **React Components** | Each UI element is a self-contained component with props and state |
| **WebSocket Client** | `AgentPanel.jsx` — `new WebSocket(url)` connects, `onmessage` updates UI |
| **Real-Time UI** | Status badge updates instantly when harness emits — no page refresh |
| **REST API calls** | `fetch()` to assign ticket, approve plan, trigger fine-tuning |
| **State Management** | `useState`, `useEffect` — React fundamentals |

---

### Concept Master Map — Everything in One View

```
CONCEPT                  PHASE    FILE                      HOW
─────────────────────────────────────────────────────────────────────────
FastAPI                    1      main.py                   Async web framework
PostgreSQL                 1      db/session.py             Primary DB, all envs
SQLAlchemy (async)         1      db/models.py              ORM, asyncpg driver
State Machine              1      agent/harness.py          JobStatus enum + transitions
Crash Recovery             1      agent/harness.py          Read DB on startup, resume
Timeout Watchdog           1      agent/harness.py          asyncio.wait_for per step
Exponential Backoff        1      agent/harness.py          sleep(2**n) on retry
Async/Await                1      everywhere                Non-blocking I/O throughout
MCP                        2      integrations/*.py         Standard tool-call protocol
Tool Use                   2      integrations/*.py         Agent calls JIRA/GitHub as tools
RAG (basic)                2      agent/context.py          Keyword extract → inject context
Token Counting             2      agent/context.py          tiktoken, filter if over limit
LLM API (Anthropic)        3      agent/orchestrator.py     messages.create() direct call
LLM API (OpenAI)           3      agent/orchestrator.py     chat.completions.create()
System Prompt              3      agent/planner.py          Loaded from DB, injected first
Temperature                3      agent/orchestrator.py     0.1 code / 0.6 planning
Structured Output          3      agent/planner.py          Prompt→JSON→Pydantic parse
Prompt Engineering         3      agent/*.py                Per-step prompts, rules, overrides
Fine-Tune Layer 1          3      db/models.py              Prompts stored + versioned in DB
Fine-Tune Layer 2          3      db/models.py              Params stored per step in DB
Few-Shot Prompting         3      agent/orchestrator.py     Past jobs injected as examples
REST API Design            4      api/*.py                  Resources, verbs, status codes
WebSocket                  4      api/ws.py                 Real-time push to dashboard
Dependency Injection       4      api/*.py                  FastAPI Depends() for DB session
CORS                       4      main.py                   Allow React frontend origin
Fine-Tune Layer 3 (ML)     5      agent/finetuning.py       JSONL → OpenAI fine-tune API
JSONL                      5      agent/finetuning.py       Training data format
Feedback Loop              5      agent/finetuning.py       Approved jobs → training examples
pgvector                   6      db/models.py              vector(1536) column in PostgreSQL
Embeddings                 6      agent/search.py           text → float[] via OpenAI API
Hierarchical Indexing      6      agent/search.py           Sentence search → chunk return
Hybrid Search              6      agent/search.py           Vector + tsvector + RRF fusion
Contextual Embeddings      6      agent/search.py           Doc summary prepended to sentence
IVFFlat Index              6      db/migration              Fast approx nearest-neighbour
React + WebSocket          7      frontend/src/             Live status in browser
```

---

### Why No LangChain?

LangChain is a popular framework. You should know it. But we are NOT using it
as the foundation of this project, and here is exactly why:

| What LangChain gives you | What we build instead | Why building > using |
|---|---|---|
| `LLMChain` | `orchestrator.py` | You understand every token sent |
| `PromptTemplate` | `planner.py` system prompt loading | You control the exact string |
| `AgentExecutor` | `harness.py` state machine | You own crash recovery + state |
| `VectorStoreRetriever` | `agent/search.py` | You understand why chunking fails |
| `ConversationMemory` | `db/models.py` EventLog | Yours is in a real DB, queryable |

**After Phase 3, LangChain will be trivial to you.** You will look at any LangChain
code and immediately know what is happening under the hood — because you wrote
every piece yourself first. That understanding is what makes you hireable.

---

### Where LangChain WOULD appear (optional Phase 8)

If we added a Phase 8 "LangChain Refactor", we would:
- Replace `orchestrator.py` with `LLMChain`
- Replace `agent/search.py` retrieval with `VectorStoreRetriever`
- Compare outputs and performance

This is optional and educational. The core product works without it.

---

## Codebase Context: AgenticStack

To understand any target repository before making changes, we use the
`agenticstackfile` pip package (PyPI: https://pypi.org/project/agenticstackfile/).

Install it with:

```bash
pip install 'agenticstackfile[all]'
```

It analyzes a Python repository using AST and optionally LLMs, and generates
`AgenticStack.txt` — a structured codebase map containing:

- File classification (models, views, serializers, services, utils, etc.)
- Class and function inventory per file
- Framework detection (Django, Flask, FastAPI, plain Python)
- Step-by-step change guides using actual file paths
- Auto-sync via `agenticstack watch` when files change

**The agent must always read `AgenticStack.txt` of the target repo before
touching any code. No exceptions. Do not rewrite or duplicate this package.**

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    React Dashboard (Frontend)                │
│  - Lists all JIRA tickets assigned to logged-in user        │
│  - Real-time status updates per ticket via WebSocket        │
│  - Admin can view title + description of any ticket         │
│  - User can assign a ticket to the agent                    │
│  - Agent explains plan → user approves → agent executes     │
│  - Fine-tuning settings panel (prompts, params, models)     │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST API + WebSocket
┌──────────────────────────▼──────────────────────────────────┐
│                   Python Backend (FastAPI)                   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                  Agent Harness                       │   │
│  │  - Job queue (one job per ticket)                   │   │
│  │  - Step state machine (plan→approve→execute→PR)     │   │
│  │  - Crash recovery + resume from last known state    │   │
│  │  - Timeout watchdog per step                        │   │
│  │  - Full event log with timestamps (audit trail)     │   │
│  │  - Real-time status → WebSocket → Dashboard         │   │
│  └──────────────────────────┬──────────────────────────┘   │
│                             │                               │
│  ┌──────────────────────────▼──────────────────────────┐   │
│  │               Context Engineer                       │   │
│  │  - Reads AgenticStack.txt from target repo          │   │
│  │  - Extracts only sections relevant to the ticket    │   │
│  │  - Reads JIRA ticket: title, description, criteria  │   │
│  │  - Reads recent GitHub commits on main (last 10)    │   │
│  │  - Checks open PRs for file conflicts               │   │
│  │  - Estimates token count, filters if over limit     │   │
│  │  - Packages into one focused context object         │   │
│  └──────────────────────────┬──────────────────────────┘   │
│                             │                               │
│  ┌──────────────────────────▼──────────────────────────┐   │
│  │             Agent Orchestrator                       │   │
│  │  - Receives focused context from context engineer   │   │
│  │  - Loads active prompt config + model parameters   │   │
│  │  - Runs: planner → executor → PR raiser             │   │
│  │  - Reports each step result back to harness         │   │
│  │  - Supports Anthropic Claude and OpenAI as LLMs     │   │
│  │  - Supports fine-tuned model IDs                    │   │
│  └──────────────────────────┬──────────────────────────┘   │
│                             │                               │
│  ┌──────────────────────────▼──────────────────────────┐   │
│  │             Fine-Tuning Engine                       │   │
│  │  - Stores feedback (approved/rejected plans)        │   │
│  │  - Exports training data in JSONL format            │   │
│  │  - Triggers OpenAI or Anthropic fine-tuning jobs    │   │
│  │  - Tracks fine-tuned model IDs and versions         │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└──────────────────────────┬──────────────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
    ┌─────▼──────┐  ┌──────▼──────┐  ┌─────▼───────────────┐
    │ JIRA MCP   │  │ GitHub MCP  │  │ agenticstackfile    │
    │            │  │             │  │ (PyPI pip package)  │
    └────────────┘  └─────────────┘  └─────────────────────┘
```

---

## Agent Harness (Long-Running Agent Management)

Every agent job runs inside a harness. This is the most critical layer —
without it, long-running agent tasks (which can take minutes) become
unobservable black boxes.

### State Machine

Each ticket assigned to the agent moves through these states, persisted in DB:

```
QUEUED
  → GATHERING_CONTEXT
  → AWAITING_CLARIFICATION   (only if ticket is ambiguous)
  → PLANNING
  → AWAITING_APPROVAL        (user must approve before any code is written)
  → EXECUTING
  → RAISING_PR
  → COMPLETED

At any state → FAILED
At any state → TIMED_OUT
```

### Harness Responsibilities

- **State persistence** — every state transition saved to DB immediately
- **Crash recovery** — on restart, read DB state and resume from last good step.
  If a job was at EXECUTING and the process crashed, it resumes at EXECUTING,
  not from QUEUED.
- **Timeout watchdog** — each step has a max allowed time. If exceeded,
  job is marked TIMED_OUT and user is notified via dashboard.
- **Retry logic** — transient failures (API rate limits, network timeouts)
  are retried with exponential backoff before marking as FAILED.
- **Event log** — every state transition logged with timestamp, step name,
  and detail. Full audit trail per ticket, queryable from dashboard.
- **WebSocket emitter** — every state change immediately pushes a real-time
  update to the dashboard so the user always sees current status.

---

## Context Engineer

Before the agent receives any prompt, the context engineer builds a focused
context package. The agent never receives raw, unfiltered data directly.

### Why This Matters

Giving the agent an entire codebase hits token limits and degrades output
quality. Focused context = better decisions, lower API cost, faster execution.

### Steps the Context Engineer Runs

1. Read full `AgenticStack.txt` from the target repository
2. Extract only sections relevant to the ticket — matched by keywords
   in the ticket title and description (e.g. if ticket mentions "serializer",
   pull only the serializer and related model sections)
3. Read JIRA ticket: title, description, acceptance criteria, linked tickets
4. Read recent GitHub commits on main branch (last 10)
5. Check for open PRs that touch the same files (conflict detection)
6. Package everything into a single structured context object
7. Estimate token count — if over the model's limit, further filter
   by relevance score, prioritizing closest-match sections

---

## Agent Fine-Tuning

The agent supports three layers of fine-tuning, each independently configurable.
Together they allow the agent to get smarter over time and adapt to your team's
specific codebase, conventions, and preferences.

---

### Layer 1 — Prompt Customization

The agent's system prompt is not hardcoded. It is stored in the database and
editable from the dashboard settings panel at any time.

**What can be customized:**

- **System prompt** — the base instructions the agent receives at the start of
  every job. Controls tone, format, and general behavior.
- **Per-step prompts** — separate prompts for the planner, executor, and PR raiser.
  For example: "Always write unit tests alongside implementation code."
- **Custom rules** — project-specific injections appended to every prompt.
  Examples:
  - "Always use async/await. Never use synchronous DB calls."
  - "Follow PEP8 strictly. Max line length is 88 characters (Black formatter)."
  - "Never modify migration files directly."
- **Per-repo overrides** — place a `.agentictask.md` file in the root of any
  target repository. The context engineer will detect and inject it automatically.
  This lets each repo have its own agent instructions without touching the dashboard.

**Storage:** Prompt configs are stored in the DB with version history.
You can roll back to a previous prompt version at any time.

---

### Layer 2 — Model Parameters

The LLM call at each step is configurable via parameters stored in the DB
and editable from the dashboard.

| Parameter | Description | Recommended values |
|---|---|---|
| `temperature` | Randomness of output. Lower = more deterministic. | 0.0–0.2 for code, 0.4–0.7 for planning |
| `max_tokens` | Maximum tokens the model can output per step | 2048 for planning, 4096 for execution |
| `top_p` | Nucleus sampling — limits token selection pool | 0.9–1.0 |
| `frequency_penalty` | Reduces repetition in output (OpenAI only) | 0.0–0.3 |

**Per-step configuration:** Each agent step (planner, executor, PR raiser)
can have independent parameter sets. Planning needs more creativity (higher
temperature), code execution needs precision (lower temperature).

**Storage:** Parameter sets are saved to DB per step per provider.
Changes take effect on the next job run — no restart required.

---

### Layer 3 — Actual ML Fine-Tuning

The system collects real usage data over time and uses it to train a custom
model that is specialized for your codebase and team's patterns.

**How training data is collected:**

Every completed agent job generates a training record:

```
Input:  JIRA ticket + AgenticStack context + repo conventions
Output: The plan the agent generated + the code it wrote
Label:  approved (user clicked Approve) or rejected (user modified or declined)
```

Only approved jobs are used as positive training examples.
Rejected jobs are stored separately for analysis but not used in training.

**Training data format (JSONL — OpenAI compatible):**

```json
{
  "messages": [
    {"role": "system", "content": "<system prompt used>"},
    {"role": "user", "content": "<ticket + context package>"},
    {"role": "assistant", "content": "<plan + code the agent produced>"}
  ]
}
```

**Fine-tuning providers:**

| Provider | API | Notes |
|---|---|---|
| OpenAI | `POST /v1/fine_tuning/jobs` | Supports GPT-4o mini fine-tuning. Most mature API. |
| Anthropic | Fine-tuning API (when available) | Check Anthropic docs for current availability. |

**Fine-tuning workflow:**

1. Dashboard shows count of approved training examples collected
2. User triggers fine-tuning job from settings panel (minimum 10 examples recommended)
3. Backend exports training data as JSONL, submits to provider API
4. Provider trains the model (async — takes minutes to hours)
5. Backend polls for completion, stores the returned fine-tuned model ID in DB
6. User can switch any step to use the fine-tuned model from the dashboard
7. Fine-tuned model IDs are versioned — old versions remain available for rollback

**Fine-tuning engine responsibilities (`backend/agent/finetuning.py`):**
- Collect and store training examples per job
- Export training data as JSONL
- Submit fine-tuning jobs to OpenAI or Anthropic API
- Poll job status and store returned model ID
- Version and manage fine-tuned model registry

---

## Agent Workflow (Per Ticket)

### Step 1 — Gather Context

- Context engineer builds the focused context package (see above)
- Agent reads the package: codebase map + ticket details + recent activity
- If anything in the ticket is ambiguous, missing, or contradictory —
  agent MUST ask the user via dashboard before proceeding.
- Agent never assumes or hallucinates intent. No exceptions.

### Step 2 — Plan (requires user approval)

Agent generates a written plan containing:
- Which files will be created or modified (with exact paths)
- What functions and classes will change
- Why each change is needed, linked to ticket requirements
- Estimated risk level: low / medium / high

Plan is displayed in the dashboard. Code execution does NOT start until
the user explicitly clicks Approve.

### Step 3 — Execute

- Agent checks if branch `agentictask/{ticket-id}-{slug}` already exists
- If yes: checkout that branch and continue
- If no: create it from main, then proceed
- Agent writes all code changes
- Agent commits with message: `[{ticket-id}] {ticket title}`
- All changes stay on the feature branch — main/master is never touched directly

### Step 4 — Raise PR

- Agent opens a GitHub Pull Request
- PR title: `[{ticket-id}] {ticket title}`
- PR description: auto-generated summary of all changes with reasoning
- PR body includes a link back to the JIRA ticket
- JIRA ticket status is automatically updated to `In Review`

---

## Agent Rules (Non-Negotiable)

1. **No hallucination** — if the ticket is unclear, ask first. Never guess intent.
2. **Read AgenticStack.txt first** — always, before any code work, no exceptions.
3. **Never touch main/master directly** — all work on feature branches only.
4. **Plan before code** — user must approve the written plan before execution.
5. **One ticket = one branch = one PR** — never mix work across tickets.
6. **Update JIRA status at each step** — In Progress → In Review automatically.
7. **Log everything** — every action goes through the harness event log.
8. **Context engineer first** — agent never receives raw unfiltered data.

---

## Tech Stack

| Layer | Technology | Why This Choice |
|---|---|---|
| Frontend | React | Industry standard, component model maps well to ticket cards + panels |
| Backend | FastAPI (Python) | Async-native, automatic API docs, best Python framework for AI backends |
| Real-time updates | WebSocket (via FastAPI) | Persistent connection = instant push. HTTP polling would be too slow and wasteful |
| JIRA integration | JIRA MCP | MCP is the standard protocol for giving AI agents access to external tools |
| GitHub integration | GitHub MCP | Same reason — MCP lets the agent call GitHub actions as structured tool calls |
| Codebase context | agenticstackfile (PyPI) | Pre-built AST analysis — no point reinventing this |
| Agent LLM | Anthropic Claude API or OpenAI API | Both supported; configurable per deployment |
| Fine-tuning | OpenAI Fine-Tuning API / Anthropic Fine-Tuning API | Allows model to learn from your specific codebase over time |
| State persistence | PostgreSQL (all environments) | One database everywhere — no SQLite/PostgreSQL divergence, pgvector works from day 1 |
| Vector search | pgvector (PostgreSQL extension) | No separate vector DB needed — semantic search lives inside the same PostgreSQL instance |
| ORM | SQLAlchemy (async) | Python standard. asyncpg driver for async PostgreSQL. Declarative models = clean schema. |

---

## Project Structure (Target)

```
agentictask/
├── backend/
│   ├── main.py                      # FastAPI app entry point
│   ├── agent/
│   │   ├── harness.py               # State machine, crash recovery, watchdog
│   │   ├── orchestrator.py          # Main agent workflow controller
│   │   ├── planner.py               # Step 2: plan generation
│   │   ├── executor.py              # Step 3: code writing and committing
│   │   ├── context.py               # Context engineer
│   │   └── finetuning.py            # Training data collection + fine-tune jobs
│   ├── integrations/
│   │   ├── jira.py                  # JIRA MCP wrapper
│   │   └── github.py                # GitHub MCP wrapper
│   ├── api/
│   │   ├── tickets.py               # Ticket CRUD endpoints
│   │   ├── agent.py                 # Agent control endpoints (assign, approve, stop)
│   │   ├── settings.py              # Prompt config + model parameter endpoints
│   │   ├── finetuning.py            # Fine-tuning trigger + status endpoints
│   │   └── ws.py                    # WebSocket handler for real-time updates
│   ├── db/
│   │   ├── models.py                # Job, EventLog, PromptConfig, TrainingExample DB models
│   │   └── session.py               # DB connection and session management
│   └── config.py                    # Environment variables and app settings
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Dashboard.jsx        # Main ticket board
│   │   │   ├── TicketCard.jsx       # Individual ticket with status
│   │   │   ├── AgentPanel.jsx       # Plan display + approve button + live status
│   │   │   ├── StatusBadge.jsx      # Real-time status indicator
│   │   │   └── Settings/
│   │   │       ├── PromptEditor.jsx     # Edit system prompts and rules
│   │   │       ├── ModelParams.jsx      # Configure temperature, max tokens, etc.
│   │   │       └── FineTuning.jsx       # Training data count + trigger fine-tune job
│   │   └── App.jsx
│   └── package.json
├── pyproject.toml
├── .env.example
└── CLAUDE.md                        # This file
```

---

## Build Phases

### Phase 1 — Backend Skeleton (current)
FastAPI app + DB models + Agent Harness with full state machine.
Nothing else is built until the harness is solid and tested.
Files: `main.py`, `config.py`, `db/models.py`, `db/session.py`, `agent/harness.py`

### Phase 2 — Integrations + Context Engineer
JIRA MCP wrapper, GitHub MCP wrapper, agenticstackfile reader.
Context engineer that packages everything into one focused object.
Files: `integrations/jira.py`, `integrations/github.py`, `agent/context.py`

### Phase 3 — Agent Orchestrator + Planner + Executor
The actual AI calls. Planner generates plan, executor writes code.
PR raiser opens GitHub PR and updates JIRA.
Files: `agent/orchestrator.py`, `agent/planner.py`, `agent/executor.py`

### Phase 4 — API Layer + WebSocket
REST endpoints the frontend calls. WebSocket handler for real-time updates.
Files: `api/tickets.py`, `api/agent.py`, `api/settings.py`, `api/ws.py`

### Phase 5 — Fine-Tuning Engine
Training data collection, JSONL export, fine-tuning job submission.
Files: `agent/finetuning.py`, `api/finetuning.py`

### Phase 6 — High-Accuracy Semantic Search (pgvector + Hybrid)
Add semantic similarity search inside PostgreSQL using the pgvector extension.
No separate vector database — everything lives in the same PostgreSQL instance.

Strategy: Hierarchical Indexing + Sentence Window Retrieval + Hybrid Search.
See the "Vector Search Architecture" section below for full details.

### Phase 7 — React Frontend
Dashboard, ticket cards, agent panel, settings panel, fine-tuning UI.

---

## Environment Variables

Copy `.env.example` to `.env` and fill in all values before running.

```env
# AI Providers — at least one is required
ANTHROPIC_API_KEY=
OPENAI_API_KEY=

# Which provider to use by default: anthropic or openai
AI_PROVIDER=anthropic

# JIRA
JIRA_BASE_URL=https://yourcompany.atlassian.net
JIRA_EMAIL=you@yourcompany.com
JIRA_API_TOKEN=
JIRA_PROJECT_KEY=

# GitHub
GITHUB_TOKEN=
GITHUB_REPO_OWNER=
GITHUB_REPO_NAME=

# AgenticStack — path to the local repo this agent will work on
TARGET_REPO_PATH=

# Database — PostgreSQL only (no SQLite)
# Local dev: run "docker compose up -d db" to start PostgreSQL
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/agentictask
```

---

## What Has Not Been Built Yet

Everything in this repository is new. Start from scratch.

Do not rewrite or vendor the `agenticstackfile` pip package.
Install it from PyPI and use it as-is: https://pypi.org/project/agenticstackfile/

---

## AI Concepts You Will Learn Building This Project

This section explains every major AI/ML concept this project touches.
Read it when you need to explain a decision to someone.

---

### 1. Tokens — What They Are and Why They Matter

A token is roughly 0.75 words. "Hello world" = 2 tokens. "authentication" = 1 token.

**Why tokens matter:**
- Every LLM has a context window limit (e.g. Claude: 200k tokens, GPT-4: 128k)
- You pay per token (input + output)
- Larger context = slower response + higher cost
- Too much irrelevant context degrades output quality

**In this project:** The context engineer counts tokens before sending to the LLM.
If we're over the limit, we filter out less relevant sections.
This is why the context engineer exists — to be the token budget manager.

---

### 2. Context Window

The context window is the total amount of text (in tokens) the LLM can see at once.
It includes: system prompt + conversation history + your input + the model's output.

**Think of it like:** Working memory. The model can only "think about" what fits
inside this window. Anything outside it is invisible to the model.

**In this project:** We build a focused context package that fits inside the window.
We never dump the entire codebase in — we extract only what's relevant to the ticket.

---

### 3. Temperature

A number between 0.0 and 2.0 that controls how random the model's output is.

- `0.0` = completely deterministic. Same input → same output every time. Best for code.
- `0.7` = balanced. Good for planning, where some creativity is useful.
- `1.5+` = very random. Good for creative writing. Bad for code.

**In this project:** We use low temperature (0.0–0.2) for the executor (writing code)
and higher temperature (0.4–0.7) for the planner (generating plans needs some creativity).
Each step has its own temperature setting stored in the DB.

---

### 4. Top-P (Nucleus Sampling)

Works alongside temperature. Instead of sampling from all possible next tokens,
top-p limits sampling to the smallest set of tokens whose combined probability
exceeds the threshold P.

- `top_p = 1.0` = consider all tokens (no restriction)
- `top_p = 0.9` = only consider the top 90% probability mass of tokens

**Simple version:** Temperature controls HOW random. Top-P controls WHICH options
are even considered before randomness is applied.

**In this project:** We keep top_p at 0.9–1.0 for all steps. Temperature is the
primary dial we adjust per step.

---

### 5. System Prompt

A special instruction given to the LLM before any user message.
It sets the model's persona, rules, and behavior for the entire conversation.

**Example:**
```
System: You are a senior software engineer. You write clean Python code.
        You never modify database migration files directly.
        You always write unit tests alongside implementation.
```

**In this project:** The system prompt is stored in the DB, editable from the
dashboard, and injected at the start of every agent job. This is Layer 1 fine-tuning.
Each step (planner, executor, PR raiser) can have its own system prompt.

---

### 6. Fine-Tuning

Fine-tuning = taking a pre-trained model (like GPT-4o or Claude) and training it
further on your own data so it learns your specific patterns.

**Three types used in this project:**

**Layer 1 — Prompt tuning:** Change the system prompt to guide behavior.
No model weights change. Instant. Free. Limited ceiling.

**Layer 2 — Parameter tuning:** Adjust temperature, max_tokens, top_p.
Control how the model generates without retraining. Still no weight changes.

**Layer 3 — Actual ML fine-tuning:** Upload training data (JSONL) to OpenAI or
Anthropic. They retrain model weights on your data. Result: a custom model ID
that behaves exactly like your team wants.

**Why fine-tune?** A general model doesn't know your codebase, your conventions,
or your team's preferences. Fine-tuning teaches it all of that.

**In this project:** Every time a user approves a plan, that job becomes a
training example. Over time, the model learns what "good" looks like for your team.

---

### 7. JSONL (JSON Lines)

A file format where each line is a separate valid JSON object.
Used as the universal training data format for LLM fine-tuning.

```jsonl
{"messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}
{"messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}
```

**Why not regular JSON?** A regular JSON array requires loading the entire file
into memory to parse. JSONL can be processed line by line — critical for large
training datasets.

---

### 8. RAG — Retrieval Augmented Generation

RAG is a pattern where instead of relying purely on the model's training data,
you first retrieve relevant information from an external source and inject it
into the context before calling the LLM.

**Without RAG:**
```
User: "How does our auth system work?"
LLM: [guesses based on training data — may hallucinate]
```

**With RAG:**
```
1. Search codebase for auth-related files → retrieve top 5 results
2. Inject those files into context
3. User: "How does our auth system work?"
4. LLM: [answers using actual retrieved code — no hallucination]
```

**In this project:** The context engineer IS a RAG implementation.
It retrieves relevant sections of AgenticStack.txt based on the ticket keywords
and injects them into the agent's context. This prevents hallucination about
code that doesn't exist.

---

### 9. Vector Database

A database that stores and searches by meaning (semantic similarity), not just
exact keyword matches. In this project we use **pgvector** — a PostgreSQL
extension — so there is no separate vector database. Everything lives in one
PostgreSQL instance.

**How basic vector search works:**
1. Convert text to a vector (array of ~1536 numbers) using an embedding model
2. Store that vector alongside the original text in PostgreSQL
3. To search: convert query to a vector, find stored vectors that are mathematically close
4. Close vectors = similar meaning, even if the words are completely different

**Example:**
- Stored: "fix authentication error on login page"
- Query: "user can't sign in"
- Keyword search: 0 matches (no shared words)
- Vector search: high similarity match (same meaning)

**Why basic chunking is not enough (the problem you identified):**

Standard RAG splits text into fixed-size chunks (e.g. 500 tokens) and embeds
each chunk. Problems:
- A relevant sentence may be split across two chunks — both score medium, neither scores high
- A chunk matches but the relevant part is one sentence buried inside it — the LLM gets noisy context
- Exact terms like "AuthenticationError" have no semantic neighbours — vector search misses them

**Solution used in this project: Three-layer search strategy**

See the "Vector Search Architecture" section below for the full implementation.

---

### 10. Embeddings

Embeddings are the numerical vector representations used in vector search.
They are produced by embedding models — separate, smaller models distinct from LLMs.

**Examples:**
- OpenAI: `text-embedding-3-small` (1536 dimensions) — best quality/cost ratio
- Open-source: `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions, runs locally)
- Anthropic: no public embedding model yet — use OpenAI embeddings alongside Claude

**In this project (Phase 6):** We embed at two granularities:
- Each individual sentence in a document → for precision matching
- Each parent paragraph/chunk → for context retrieval after a sentence match

On new tickets, we embed the ticket and find the k-nearest past jobs to inject
as few-shot examples into the agent's context.

---

### 11. Agent Harness Pattern

A harness is a wrapper around a long-running agent that makes it:
- Observable (you can see what it's doing at any point)
- Resumable (crash → restart from last checkpoint, not from zero)
- Controllable (pause, approve, cancel at defined points)
- Auditable (full event log of every action with timestamps)

**Why this is trending:** As AI agents do more complex multi-step work,
the harness pattern is becoming as fundamental as try/catch in regular programming.
Without it, agents are black boxes. With it, they are production-grade systems.

**In this project:** Every agent job runs inside the harness. The harness persists
state to DB, runs the timeout watchdog, handles retries, and emits WebSocket events.

---

### 12. MCP — Model Context Protocol

MCP is an open protocol (by Anthropic) that standardizes how AI agents connect
to external tools and data sources.

**Without MCP:** Every tool integration is custom code. JIRA integration looks
completely different from GitHub integration. Agents can't be composed.

**With MCP:** Every tool exposes a standard interface. The agent calls tools
the same way regardless of whether it's JIRA, GitHub, Slack, or a database.

**In this project:** JIRA MCP and GitHub MCP are used so the agent can read
tickets and raise PRs using the same tool-call interface as any other MCP server.

---

### 13. WebSocket vs REST API

**REST API:** Client sends request → server responds → connection closes.
Good for: CRUD operations, one-time queries.

**WebSocket:** Client and server open a persistent connection. Either side can
send messages at any time. Good for: real-time updates, live status, chat.

**In this project:** REST API is used for commands (assign ticket, approve plan,
trigger fine-tuning). WebSocket is used for status updates — when the harness
transitions state, it instantly pushes the new status to the dashboard.
Without WebSocket, the dashboard would have to poll every second (wasteful).

---

### 14. Async/Await (Python)

Async code allows a program to handle multiple operations without blocking.
Instead of waiting for one operation to finish before starting the next,
async code suspends and lets other work happen while waiting.

**Why this matters for AI agents:**
- LLM API calls take 2–30 seconds. Without async, your server is frozen for that entire time.
- With async, the server can handle other requests while waiting for the LLM.

**In this project:** FastAPI is async-native. Every database call, LLM call,
and external API call uses `async/await`. This allows the server to manage
multiple agent jobs concurrently without threading complexity.

---

### 15. State Machine

A state machine is a model where a system is always in exactly one of a defined
set of states, and transitions between states are triggered by specific events.

**Why use a state machine for the harness?**
- It makes all valid transitions explicit — you can never accidentally jump from
  QUEUED to RAISING_PR
- It makes crash recovery simple — read the current state from DB, resume from there
- It makes the system auditable — every transition is logged

**In this project:** The harness implements a state machine where each job
progresses through defined states. Invalid transitions are rejected. Every
transition is persisted immediately and emitted over WebSocket.

---

### 16. Exponential Backoff

A retry strategy where the wait time between retries increases exponentially.

```
Attempt 1 fails → wait 1 second → retry
Attempt 2 fails → wait 2 seconds → retry
Attempt 3 fails → wait 4 seconds → retry
Attempt 4 fails → wait 8 seconds → retry
Give up → mark as FAILED
```

**Why exponential and not fixed?** If an API is rate-limited or overloaded,
hammering it with constant retries makes the problem worse. Exponential backoff
gives the system time to recover and reduces load on the external service.

**In this project:** Used for LLM API calls, JIRA API calls, and GitHub API calls
inside the harness. Only network/rate-limit errors are retried — logic errors (bad
prompt, invalid plan format) are not.

---

## Why Each Technology Was Chosen

### FastAPI over Flask or Django

| | FastAPI | Flask | Django |
|---|---|---|---|
| Async support | Native | Bolted on | Bolted on |
| WebSocket | Built-in | Via extensions | Via Channels (complex) |
| Auto API docs | Yes (Swagger) | No | No |
| Speed | Very fast | Medium | Slow |
| Best for | AI backends, APIs | Simple scripts | Full-stack web apps |

FastAPI is the standard choice for AI/ML backends in 2025. It was built for exactly this use case.

### SQLAlchemy over raw SQL or other ORMs

- Async support via `asyncpg` driver — essential for a FastAPI backend
- Handles connection pooling, transactions, and session management
- Industry standard in Python — every Python developer knows it
- Declarative model definitions match DB schema 1:1

### PostgreSQL from Day 1 (no SQLite at all)

Using SQLite in dev and PostgreSQL in prod creates hidden divergence:
- SQLite is not concurrent — it locks the whole DB file on writes. PostgreSQL uses row-level locking.
- pgvector (Phase 6) only works in PostgreSQL. Starting with SQLite means migrating later.
- JSON column behaviour, full-text search syntax, and index types differ between the two.

Decision: PostgreSQL everywhere from Phase 1. Use Docker for local setup — one command gives
you a local PostgreSQL instance identical to production. No surprises when you deploy.

---

## Vector Search Architecture (Phase 6)

Standard chunking fails because it trades precision for coverage.
This project uses a three-layer strategy that achieves both.

---

### Layer 1 — Hierarchical Indexing (Sentence + Chunk)

Every document (AgenticStack.txt section, past job plan, ticket description)
is indexed at two granularities simultaneously:

**Sentence level (child):**
- Split the document into individual sentences
- Embed each sentence separately → store as a row in `sentence_embeddings` table
- Each row has: `sentence_text`, `embedding vector(1536)`, `parent_chunk_id`

**Chunk level (parent):**
- Split the document into paragraphs/sections (~300–500 tokens)
- Embed each chunk → store as a row in `chunk_embeddings` table
- Each chunk has: `chunk_text`, `embedding vector(1536)`, `document_id`

**How search works:**
```
Query → embed query
     → search sentence_embeddings for top-K matching sentences  (precision)
     → for each matched sentence, fetch its parent chunk         (context)
     → deduplicate chunks
     → return chunks to LLM (not raw sentences)
```

Result: You find the exact matching sentence (precision), but send the surrounding
paragraph to the LLM (context). Best of both granularities.

---

### Layer 2 — Hybrid Search (Vector + Keyword)

Pure vector search fails on exact terms. "AuthenticationError", "ticket AT-42",
"function validate_user" — these have no semantic neighbours. Keyword search finds them.

**Implementation:**
- PostgreSQL built-in full-text search (`tsvector` + `tsquery`) for keyword matching
- pgvector cosine similarity for semantic matching
- Both run as a single SQL query
- Scores combined using **Reciprocal Rank Fusion (RRF)**

**RRF formula:**
```
rrf_score = 1/(k + vector_rank) + 1/(k + keyword_rank)
where k = 60 (standard constant)
```

RRF does not require score normalisation — it only needs rank position from each system.
The result is a single merged ranked list that rewards documents appearing high in both.

**Example showing why both are needed:**

| Query | Vector search finds | Keyword search finds |
|---|---|---|
| "user can't sign in" | "authentication error on login" ✓ | Nothing (no shared words) ✗ |
| "AuthenticationError class" | Generic auth files (maybe) | Exact class definition ✓ |
| "fix the bug from ticket AT-42" | Similar bug tickets ✓ | Exact ticket AT-42 ✓ |

Hybrid search wins every row.

---

### Layer 3 — Contextual Embeddings (Late Chunking)

Standard embedding: embed the sentence in isolation.
Problem: "it was fixed in the next line" — "it" has no meaning without context.

**Contextual embedding:** Before embedding each sentence, prepend a short summary
of the document it came from:

```
"[Document: AgenticStack.txt > Authentication section]
The validate_user function checks the JWT token against the database.
It was fixed in the next line."
```

Now the embedding of "It was fixed in the next line" carries document context.
This dramatically improves recall for sentences that use pronouns or relative references.

Implementation: prepend `document_summary + "\n" + sentence_text` before calling
the embedding model. Document summary is generated once per document using the LLM.

---

### Full pgvector Schema (Phase 6)

```sql
-- Enable the extension (run once)
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- for keyword search

-- Parent chunks
CREATE TABLE chunk_embeddings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL,
    chunk_text  TEXT NOT NULL,
    embedding   vector(1536),
    ts_vector   tsvector GENERATED ALWAYS AS (to_tsvector('english', chunk_text)) STORED,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Child sentences (point back to parent chunk)
CREATE TABLE sentence_embeddings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_chunk_id UUID REFERENCES chunk_embeddings(id),
    sentence_text   TEXT NOT NULL,
    embedding       vector(1536),
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Vector index (cosine distance)
CREATE INDEX ON sentence_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX ON chunk_embeddings    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Keyword index
CREATE INDEX ON chunk_embeddings USING GIN (ts_vector);
```

---

### Why IVFFlat Index?

`ivfflat` = Inverted File with Flat quantisation. It divides the vector space into
`lists` clusters. When searching, it only checks vectors in the nearest clusters —
not all vectors. This makes search fast at scale.

Trade-off: slight accuracy loss (it might miss a vector in a nearby cluster).
For production with millions of rows, use `hnsw` index instead (more accurate, slower to build).

---

## Teaching Notes — Decisions Made During Build

### Why the Harness Exists

The agent runs multiple expensive steps (JIRA read, repo scan, planning, code writing).
Each step consumes tokens and takes time. Without a harness:

- A crash at Step 3 loses Steps 1 and 2 — you pay token cost again on retry
- No way to pause mid-flow for human approval
- No timeout control — a hung step hangs the whole server
- No visibility — user has no idea what the agent is doing

The harness saves each step result to DB immediately on completion.
On restart, it reads DB state and skips already-completed steps.
This makes the agent resumable, observable, and controllable.

### Why `AWAITING_APPROVAL` is a Separate DB State

The harness literally stops at this state — it does not proceed until an
external signal (user clicking Approve via REST API) transitions it forward.

This is not a UI concern. It is a DB state. If the server restarts while
a job is at AWAITING_APPROVAL, it stays there — it does not auto-advance.

This protects against: code being written without human sign-off, losing
the audit trail of who approved what, and inability to cancel before execution.

### Branch Logic (in EXECUTING state)

- Agent checks if branch `agentictask/{ticket-id}-{slug}` already exists
- If yes: checkout that branch and continue from where it left off
- If no: create it from main, then proceed
- Main/master is never touched directly. Ever.
- One ticket = one branch = one PR. No exceptions.

### Two-Level Codebase Reading (Context Engineer)

AgenticStack.txt gives the MAP — file names, class names, function signatures.
But the agent sometimes needs the actual code inside those functions to plan correctly.

We solved this with a two-level reading strategy:

**Level 1 — AgenticStack.txt (always)**
Reads the structured summary. Identifies which files are relevant.
Token cost: low. Coverage: full project structure.

**Level 2 — Actual file reads (targeted)**
Extracts file paths mentioned in relevant AgenticStack.txt sections.
Reads those specific files from the target repo.
Token cost: moderate. Coverage: only files relevant to the ticket.

**Token budget split:**
```
MAX_CONTEXT_TOKENS = 8000

Half    (4000) → AgenticStack.txt sections   (the map)
Quarter (2000) → Actual file contents         (the real code)
Quarter (2000) → Ticket + commits + LLM output
```

This mirrors how a senior developer works:
- First scan project structure to understand where things live
- Then open only the files that matter for this specific change
- Never read all 500 files — that's noise, not signal

Why NOT read the whole repo:
- Exceeds LLM context window immediately
- Costs far more in API tokens
- Degrades output quality — too much noise confuses the model
- AgenticStack.txt + targeted reads gives 95% of the value at 5% of the cost

### Why `_check_ambiguity()` Stops the Agent

The agent transitions to `AWAITING_CLARIFICATION` — not `PLANNING` — when:
- Ticket description is under 30 characters
- Ticket contains vague phrases like "fix it", "make it work", "look into"

This enforces Agent Rule #1: no hallucination, no guessing intent.
A vague ticket that gets planned and executed produces wrong code.
Asking first costs 30 seconds. Writing wrong code costs hours.

---

## Resume Impact — What You Learn Here

After building this project you can genuinely say you have hands-on experience with:

| Concept | Where in this project |
|---|---|
| **Agent Harness Architecture** | `agent/harness.py` — state machine, crash recovery, watchdog |
| **LLM API Integration** | `agent/orchestrator.py` — Claude + OpenAI, configurable provider |
| **Prompt Engineering** | System prompts, per-step prompts, custom rules, per-repo overrides |
| **Fine-Tuning (all 3 layers)** | Prompt tuning → parameter tuning → actual ML fine-tuning with JSONL |
| **RAG Implementation** | Context engineer — keyword extraction + relevance filtering |
| **Hierarchical Indexing** | Phase 6 — sentence-level search returning chunk-level context |
| **Hybrid Search (Vector + BM25)** | Phase 6 — pgvector cosine + PostgreSQL tsvector + RRF fusion |
| **Contextual Embeddings** | Phase 6 — document-aware sentence embeddings for high recall |
| **pgvector + IVFFlat/HNSW** | Phase 6 — production vector indexing inside PostgreSQL |
| **WebSocket (real-time systems)** | `api/ws.py` — live status updates to dashboard |
| **State Machine Design** | Harness state transitions with DB persistence |
| **Async Python** | FastAPI + SQLAlchemy async throughout |
| **MCP (Model Context Protocol)** | JIRA MCP + GitHub MCP integrations |
| **Production Database Patterns** | SQLAlchemy ORM, SQLite → PostgreSQL migration path |
| **Exponential Backoff** | Retry logic in harness for LLM + external API calls |
| **Token Management** | Context engineer token budgeting and filtering |
| **JSONL Training Data** | Fine-tuning data collection, export, and submission |

This covers the full stack of what companies building AI products need in 2025–2026.

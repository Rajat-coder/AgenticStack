# AgenticTask — Session State

> This file is updated at the end of every chat session.
> At the start of a new session: read this file + CLAUDE.md before doing anything.

---

## Current Phase

**Phase 5 — Fine-Tuning Engine**
Status: IN PROGRESS — core engine built, submit to OpenAI not yet tested

Previous: Phase 4 — COMPLETE

---

## What Has Been Done So Far

### Decisions Made
- PostgreSQL only from day 1 (no SQLite). Reason: pgvector requires it, SQLite has concurrency issues.
- No LangChain. Build from scratch for deep learning. LangChain is optional Phase 8.
- Vector search strategy: Hierarchical Indexing + Hybrid Search (vector + keyword + RRF) + Contextual Embeddings inside PostgreSQL via pgvector.
- State machine states: QUEUED → GATHERING_CONTEXT → AWAITING_CLARIFICATION → PLANNING → AWAITING_APPROVAL → EXECUTING → RAISING_PR → COMPLETED (+ FAILED / TIMED_OUT from any state).
- Branch naming: `agentictask/{ticket-id}-{slug}`
- PR commit message: `[{ticket-id}] {ticket title}`
- Run server with `python -m uvicorn` not plain `uvicorn` — venv isolation issue on this machine.
- Two-level codebase reading: AgenticStack.txt (map) + targeted actual file reads.
- Token budget: half for map, quarter for files, quarter for ticket+output.
- MCP pattern built in pure Python (direct httpx calls) — not actual MCP servers.
- System prompts stored in DB (Layer 1 fine-tuning) — seeded on first startup.
- Temperature 0.4 for planner (some creativity), 0.1 for executor (deterministic code).
- Singletons (ConnectionManager, harness) live in their own modules to avoid circular imports.
- BackgroundTasks used for harness.run_job() so HTTP response returns immediately.
- Approve flow: transition to EXECUTING first (DB commit), THEN add harness to background.

---

## Files Created (All Phases So Far)

```
backend/
├── __init__.py
├── main.py              ← FastAPI app, CORS, lifespan — now clean, just mounts routers
│                           ConnectionManager and harness removed from here
├── config.py            ← pydantic-settings, reads .env, typed settings object
│                           jira_in_review_status added
├── ws.py                ← ConnectionManager class + connection_manager singleton (NEW)
│                           Moved out of main.py to avoid circular imports
├── deps.py              ← harness singleton (AgentHarness instance) (NEW)
│                           Both main.py and api/agent.py import harness from here
├── agent/
│   ├── __init__.py
│   ├── harness.py       ← State machine, transition(), run_step(), run_job(),
│   │                       resume_crashed_jobs(), timeout watchdog, exponential backoff
│   │                       Wired to orchestrator
│   ├── context.py       ← ContextEngineer, ContextPackage, RAG pipeline,
│   │                       keyword scoring, token budgeting, two-level reading,
│   │                       ambiguity detection
│   ├── planner.py       ← AgentPlan dataclass, generate_plan(), _load_system_prompt(),
│   │                       _call_anthropic(), _call_openai(), _parse_plan()
│   ├── executor.py      ← ExecutionResult, FileChange (find/replace format), execute_plan(),
│   │                       _build_executor_prompt(), _call_openai(), _parse_execution(),
│   │                       _write_file(), _setup_branch(), _git_commit(), _git_push(),
│   │                       _build_branch_name()
│   └── orchestrator.py  ← plan_job(), execute_code(), raise_pr(), _build_pr_body()
├── api/
│   ├── __init__.py
│   ├── ws.py            ← WebSocket endpoint router (NEW)
│   │                       WebSocket endpoint moved here from main.py
│   ├── tickets.py       ← GET /tickets, GET /tickets/{id} (NEW)
│   │                       TicketResponse Pydantic model
│   ├── agent.py         ← POST /agent/assign, POST /agent/approve/{id}, (NEW)
│   │                       POST /agent/stop/{id}
│   │                       GET /agent/jobs, GET /agent/jobs/{id}
│   │                       AssignRequest, JobResponse, JobDetailResponse Pydantic models
│   └── settings.py      ← GET /settings/prompt/{step} (NEW)
│                           PUT /settings/prompt/{step} (creates new version)
│                           PromptResponse, UpdatePromptRequest Pydantic models
├── db/
│   ├── __init__.py
│   ├── models.py        ← Job, EventLog, PromptConfig, TrainingExample (SQLAlchemy ORM)
│   └── session.py       ← create_async_engine, AsyncSessionFactory, init_db(),
│                           _seed_default_prompts()
└── integrations/
    ├── __init__.py
    ├── jira.py          ← JiraTicket dataclass, JiraClient, get_ticket(), update_status(),
    │                       get_project_tickets() (NEW — fetches all tickets via JQL search)
    │                       _adf_to_text(), _extract_acceptance_criteria()
    └── github.py        ← Commit/PullRequest dataclasses, GitHubClient, get_recent_commits(),
                            get_open_prs(), branch_exists(), create_branch(), create_pr()
                            create_pr() handles 422 (PR already exists) gracefully

test_run.py              ← end-to-end test script (replaced by REST API in Phase 4)
update_prompt.py         ← one-off script (replaced by PUT /settings/prompt/{step})
pyproject.toml           ← dependencies + setuptools config
docker-compose.yml       ← PostgreSQL via Docker (not used locally — Homebrew PG used instead)
.env                     ← real secrets (gitignored)
.env.example             ← template committed to git
.gitignore               ← .env added
```

---

## Database

- PostgreSQL running locally via Homebrew on port 5432
- Database: `agentictask`
- User: `postgres` (no password)
- Tables: `jobs`, `event_logs`, `prompt_configs`, `training_examples`
- `prompt_configs` seeded with two rows: step="planner" and step="executor"
- Connection: `postgresql+asyncpg://postgres@localhost:5432/agentictask`

---

## Server

- Run: `python -m uvicorn backend.main:app --reload --port 8000`
- Health: `http://localhost:8000/health` ✓
- Swagger docs: `http://localhost:8000/docs` ← new in Phase 4, auto-generated

---

## API Endpoints (Phase 4)

```
GET  /health                        ← server alive check
GET  /tickets                       ← fetch all JIRA tickets in project
GET  /tickets/{ticket_id}           ← fetch one JIRA ticket

POST /agent/assign                  ← create job (QUEUED), start harness in background
POST /agent/approve/{job_id}        ← transition AWAITING_APPROVAL → EXECUTING, resume harness
POST /agent/stop/{job_id}           ← force any active job → FAILED
GET  /agent/jobs                    ← list all jobs (dashboard overview)
GET  /agent/jobs/{job_id}           ← one job with plan (approval screen)

GET  /settings/prompt/{step}        ← read active prompt for planner or executor
PUT  /settings/prompt/{step}        ← update prompt (creates new version, deactivates old)

WS   /ws                            ← WebSocket — server pushes status on every state change
```

---

## Collaboration Rules (follow every session)

1. **Never create files/folders/code directly.** Give exact terminal command or file content as code block. User runs it and confirms.
2. **If user says "I'll write this"** — step back, only answer questions.
3. **Teach every decision** — explain WHY before WHAT.
4. **Update CLAUDE.md** with rationale as project grows.
5. **Update this file (state.md)** at end of every session.
6. **Run server with `python -m uvicorn`** not plain `uvicorn`.

---

## What To Do Next — Phase 5 (resume here)

Phase 5 core is built. Next session:
1. Collect 10+ approved examples by running real tickets through the flow
2. Test POST /finetuning/start — submits to OpenAI, gets back fine-tune job ID
3. Test GET /finetuning/status/{job_id} — polls until training complete
4. Use returned fine_tuned_model ID in planner.py instead of "gpt-4o"

Still to fix from Phase 3:
- Executor find/replace misses — switch to unified diff format (Phase 5 or 6)

---

## Known Issues to Fix in Phase 5

- Executor find/replace sometimes misses — LLM find strings don't exactly match file content
  Fix in Phase 5: switch to unified diff format + patch application
- Model params (temperature, max_tokens) are hardcoded in planner.py and executor.py
  Fix in Phase 5: add model_params column to PromptConfig, read from DB at call time
- JIRA status update hardcoded as settings.jira_in_review_status — already in config.py ✓

---

## Teaching Progress

### Concepts user understands:
- Why harness exists (token cost, crash recovery, resumability)
- State machine — all states and transitions
- Why AWAITING_APPROVAL is a real DB state
- PostgreSQL vs SQLite decision
- Why standard RAG chunking fails + our 3-layer solution
- pyproject.toml over requirements.txt
- What __init__.py does
- Async engine, session, connection pool
- get_db() dependency injection
- Why transition() commits immediately
- How if not elif in _dispatch() enables step resumption
- VALID_TRANSITIONS enforcement
- Exponential backoff (2**attempt)
- asyncio.wait_for() for timeout
- Lifespan() vs @app.on_event
- CORS and why it's needed
- ConnectionManager and broadcast()
- MCP pattern vs actual MCP servers
- RAG = keyword extraction + section scoring + token budgeting
- tiktoken = token counter (NOT embeddings)
- Embeddings come in Phase 6 (not yet built)
- Two-level reading: AgenticStack.txt map + targeted file reads
- Why system prompt is stored in DB (Layer 1 fine-tuning)
- _seed_default_prompts() — inserts default prompts on first startup only
- is_active column — keeps prompt version history, only fetch active one
- Why two separate LLM calls (planner vs executor)
- Temperature 0.4 planner vs 0.1 executor (creativity vs precision)
- max_tokens 2048 planning vs 4096 execution (plan shorter than code)
- Why _parse_plan() returns fallback instead of crashing
- subprocess for git commands on target repo
- _setup_branch() — checkout existing or create new
- AgentPlan dataclass — holds what AI decided to do
- ExecutionResult dataclass — holds what AI actually wrote
- orchestrator.py pattern — conductor between harness and planner/executor
- Why execute_code and raise_pr are separate functions (crash boundary)
- await = current code pauses, other requests can run, resumes when done
- asyncio event loop — one chef, await lets chef help others while waiting
- Why keywords filter at section level not line level (RAG limitation)
- Why full-file rewrite causes LLM to make unintended changes
- Find/replace output format — LLM returns find+replace strings, not full files
- Layer 1 fine-tuning in action — updated executor prompt in DB without restart
- Executor prompt: "plan is the only source of truth" principle
- codebase_sections is a list of strings — one string per AgenticStack.txt section
- APIRouter — groups related routes, mounted to main app with include_router()
- Depends(get_db) — FastAPI dependency injection for DB session
- BackgroundTasks — run harness after response is sent, don't block HTTP
- Pydantic request/response models — wrong data = 422, not a crash
- HTTPException — proper way to return errors (404, 409, etc)
- Why singletons (ConnectionManager, harness) need their own module (circular import prevention)
- Approve flow ordering — transition to EXECUTING in DB BEFORE starting harness in background
- WebSocket vs REST — REST for commands, WebSocket for live status pushes
- Swagger docs — FastAPI auto-generates /docs from route definitions
- Version history for prompts — deactivate old, create new version, never delete

### Concepts not yet taught:
- Alembic migrations (when schema changes)
- pgvector SQL and indexing (Phase 6)
- React + WebSocket client (Phase 7)
- Unified diff format for executor (Phase 5 improvement)
- Model params stored in DB (Phase 5)

---

## Last Session Summary

Session 1 (2026-05-25):
- Understood architecture, decided PostgreSQL only, decided vector search strategy
- Rewrote CLAUDE.md with full roadmap, AI concepts glossary, vector search architecture
- Created state.md

Session 2 (2026-05-25):
- Built Phase 1: main.py, config.py, models.py, session.py, harness.py
- Fixed pyproject.toml setuptools issue, Docker port conflict, asyncpg missing, uvicorn venv issue
- Phase 1 COMPLETE — server running, health check, WebSocket, DB tables created

Session 3 (2026-05-25):
- Built Phase 2: jira.py, github.py, context.py
- Added two-level reading: AgenticStack.txt + actual file reads
- Wired context engineer into harness (replaced _stub_gather_context)
- Explained MCP pattern, RAG, tiktoken, token budgeting, ambiguity detection
- Phase 2 COMPLETE

Session 4 (2026-05-26):
- Started Phase 3 — Agent Brain
- Added _seed_default_prompts() to session.py
- Built planner.py and executor.py
- Explained AT-42 "Fix login bug" example end to end
- Phase 3 IN PROGRESS

Session 5 (2026-05-26):
- Completed Phase 3: built orchestrator.py, wired harness
- Fixed _extract_file_paths indentation bug (was inside class, should be module-level)
- Fixed planner JSON format (added explicit output format to user_message)
- Fixed executor find/replace format (was full file rewrite, switched to find/replace pairs)
- Fixed _git_commit to stage only written files (not entire repo)
- Added _git_push() to push branch to GitHub after commit
- Fixed GitHub 422 (PR already exists) — returns existing PR URL
- Fixed JIRA status update failure — wrapped in try/except so it doesn't kill PR step
- Updated executor system prompt via update_prompt.py (plan is source of truth principle)
- Ran full end-to-end test with real JIRA ticket AMARA-2541 — PR raised successfully
- Phase 3 COMPLETE

Session 6 (2026-05-27):
- Built and tested Phase 4 REST API layer — all endpoints working
- Created backend/ws.py — ConnectionManager singleton (moved out of main.py)
- Created backend/deps.py — harness singleton (avoids circular imports)
- Created backend/api/ws.py — WebSocket endpoint as router
- Created backend/api/tickets.py — GET /tickets, GET /tickets/{id}
- Created backend/api/agent.py — assign, approve, stop, list jobs, get job
- Created backend/api/settings.py — read/update prompts with version history
- Updated backend/main.py — clean, just mounts routers
- Added get_project_tickets() to jira.py — JQL search API
- Taught: APIRouter, BackgroundTasks, Depends, HTTPException, Pydantic models,
  approve flow ordering (transition before background task), WebSocket vs REST,
  singleton module pattern to avoid circular imports, Swagger /docs
- Fixed JIRA search endpoint (GET /rest/api/3/search deprecated → GET /rest/api/3/search/jql)
- Added GET /tickets/mine — assigned to currentUser() via JQL
- Added assigned_to field to ticket responses
- Full flow tested: assign → plan → approve → execute → PR raised via REST API
- Phase 4 COMPLETE

Session 7 (2026-05-27):
- Built Phase 5 Fine-Tuning Engine
- Added temperature, max_tokens, top_p columns to prompt_configs table
- Updated planner.py and executor.py to read params from DB instead of hardcoding
- Updated settings API to expose and update model params
- Created backend/agent/finetuning.py — save_training_example(), update_example_label(),
  get_example_counts(), export_jsonl(), start_finetune_job(), get_finetune_status()
- Created backend/api/finetuning.py — GET /finetuning/examples, POST /finetuning/export,
  POST /finetuning/start, GET /finetuning/status/{job_id}
- Updated orchestrator.py to save training example after plan is generated
- Updated api/agent.py to mark examples approved/rejected when user acts
- Added rejection_reason column to training_examples table
- Fixed: check job status BEFORE transition (was checking after, always saw FAILED)
- Rejection flow: stop with reason → saved to DB → exported in JSONL as feedback message
- Removed fake assistant correction reply — honest format: system + user + assistant + feedback
- Removed minimum approval count check from export
- Phase 5 IN PROGRESS — submit to OpenAI not yet tested

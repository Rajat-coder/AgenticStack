import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.deps import harness
from backend.db.session import engine, init_db
from backend.api.agent import router as agent_router
from backend.api.settings import router as settings_router
from backend.api.tickets import router as tickets_router
from backend.api.ws import router as ws_router
from backend.api.finetuning import router as finetuning_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting AgenticTask backend...")
    await init_db()
    logger.info("Database tables ready")
    # await harness.resume_crashed_jobs()
    # logger.info("Crash recovery complete")
    yield
    logger.info("Shutting down — closing DB connections")
    await engine.dispose()


app = FastAPI(
    title="AgenticTask",
    description="AI agent that turns JIRA tickets into GitHub PRs",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount all routers
app.include_router(tickets_router)
app.include_router(agent_router)
app.include_router(settings_router)
app.include_router(ws_router)
app.include_router(finetuning_router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
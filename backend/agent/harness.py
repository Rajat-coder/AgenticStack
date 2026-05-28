import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.agent.context import context_engineer

from backend.db.models import EventLog, Job, JobStatus
from backend.db.session import AsyncSessionFactory
from backend.agent.orchestrator import execute_code, plan_job, raise_pr

logger = logging.getLogger(__name__)

# Every valid state transition. If it is not in this map, it is illegal.
VALID_TRANSITIONS: dict[JobStatus, list[JobStatus]] = {
    JobStatus.QUEUED: [
        JobStatus.GATHERING_CONTEXT,
        JobStatus.FAILED,
    ],
    JobStatus.GATHERING_CONTEXT: [
        JobStatus.AWAITING_CLARIFICATION,
        JobStatus.PLANNING,
        JobStatus.FAILED,
        JobStatus.TIMED_OUT,
    ],
    JobStatus.AWAITING_CLARIFICATION: [
        JobStatus.PLANNING,
        JobStatus.FAILED,
    ],
    JobStatus.PLANNING: [
        JobStatus.AWAITING_APPROVAL,
        JobStatus.FAILED,
        JobStatus.TIMED_OUT,
    ],
    JobStatus.AWAITING_APPROVAL: [
        JobStatus.EXECUTING,
        JobStatus.FAILED,
    ],
    JobStatus.EXECUTING: [
        JobStatus.RAISING_PR,
        JobStatus.FAILED,
        JobStatus.TIMED_OUT,
    ],
    JobStatus.RAISING_PR: [
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.TIMED_OUT,
    ],
    JobStatus.COMPLETED: [],
    JobStatus.FAILED: [],
    JobStatus.TIMED_OUT: [],
}

# How long each step is allowed to run before TIMED_OUT
STEP_TIMEOUTS: dict[JobStatus, int] = {
    JobStatus.GATHERING_CONTEXT: 120,
    JobStatus.PLANNING: 180,
    JobStatus.EXECUTING: 300,
    JobStatus.RAISING_PR: 60,
}

MAX_RETRIES = 3

# Jobs in these states are permanently done — never resume them
TERMINAL_STATES = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.TIMED_OUT}

# Jobs in these states are waiting for human input — never auto-resume them
WAITING_STATES = {JobStatus.AWAITING_CLARIFICATION, JobStatus.AWAITING_APPROVAL}


class InvalidTransitionError(Exception):
    pass


class AgentHarness:

    def __init__(self, connection_manager=None):
        # connection_manager is None in Phase 1.
        # Wired up in Phase 4 when WebSocket is built.
        self.connection_manager = connection_manager

    # ------------------------------------------------------------------
    # Core: state transition
    # ------------------------------------------------------------------

    async def transition(
        self, db: AsyncSession, job: Job, new_status: JobStatus, detail: str | None = None,
                ) -> None:
        allowed = VALID_TRANSITIONS.get(job.status, [])
        if new_status not in allowed:
            raise InvalidTransitionError(
                f"Cannot transition {job.status} → {new_status} "
                f"for job {job.id}"
            )

        from_status = job.status
        job.status = new_status
        job.updated_at = datetime.now(timezone.utc)

        # Record when this step started so the watchdog can measure elapsed time
        if new_status not in TERMINAL_STATES and new_status not in WAITING_STATES:
            job.step_started_at = datetime.now(timezone.utc)

        event = EventLog(
            job_id=job.id,
            from_status=from_status.value,
            to_status=new_status.value,
            detail=detail,
        )
        db.add(event)

        # Commit immediately — dashboard must see the new state right now,
        # not at the end of the step (which could take minutes)
        await db.commit()

        await self._emit(job.id, new_status.value, detail)
        logger.info(
            "Job %s | %s → %s | %s",
            job.id, from_status.value, new_status.value, detail or ""
        )

    # ------------------------------------------------------------------
    # Core: run one step safely (timeout + retry)
    # ------------------------------------------------------------------

    async def run_step(
        self, job: Job, db: AsyncSession, step_status: JobStatus, step_fn: Callable[[], Awaitable[Any]],
    ) -> Any:
        timeout = STEP_TIMEOUTS.get(step_status, 120)
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                result = await asyncio.wait_for(step_fn(), timeout=timeout)
                return result

            except asyncio.TimeoutError:
                await self.transition(
                    db, job, JobStatus.TIMED_OUT,
                    f"{step_status.value} exceeded {timeout}s"
                )
                raise

            except Exception as exc:
                last_error = exc

                if not _is_retryable(exc):
                    # Not a transient error — fail immediately, no retry
                    await self.transition(db, job, JobStatus.FAILED, str(exc))
                    raise

                wait_seconds = 2 ** attempt  # 1s, 2s, 4s
                logger.warning(
                    "Job %s attempt %d/%d failed: %s. Retrying in %ds",
                    job.id, attempt + 1, MAX_RETRIES, exc, wait_seconds
                )
                job.retry_count += 1
                await db.commit()
                await asyncio.sleep(wait_seconds)

        # All retries exhausted
        await self.transition(db, job, JobStatus.FAILED, str(last_error))
        raise last_error

    # ------------------------------------------------------------------
    # Core: run a job from its current state
    # ------------------------------------------------------------------

    async def run_job(self, job_id: str) -> None:
        async with AsyncSessionFactory() as db:
            try:
                result = await db.execute(select(Job).where(Job.id == job_id))
                job = result.scalar_one_or_none()

                if job is None:
                    logger.error("Job %s not found in DB", job_id)
                    return

                if job.status in TERMINAL_STATES:
                    logger.info("Job %s already terminal (%s) — skipping", job_id, job.status)
                    return

                if job.status in WAITING_STATES:
                    logger.info("Job %s waiting for human input (%s) — skipping", job_id, job.status)
                    return

                await self._dispatch(db, job)

            except (InvalidTransitionError, asyncio.TimeoutError):
                # Already handled inside transition() / run_step()
                pass
            except Exception as exc:
                logger.exception("Unexpected crash in job %s: %s", job_id, exc)
                try:
                    async with AsyncSessionFactory() as recovery_db:
                        r = await recovery_db.execute(select(Job).where(Job.id == job_id))
                        j = r.scalar_one_or_none()
                        if j and j.status not in TERMINAL_STATES:
                            await self.transition(recovery_db, j, JobStatus.FAILED, str(exc))
                except Exception:
                    logger.exception("Failed to mark job %s as FAILED after crash", job_id)

    # ------------------------------------------------------------------
    # Dispatcher — drives job through steps sequentially
    # ------------------------------------------------------------------

    async def _dispatch(self, db: AsyncSession, job: Job) -> None:
        context_package = None

        # STEP 1a — transition QUEUED → GATHERING_CONTEXT
        if job.status == JobStatus.QUEUED:
            await self.transition(db, job, JobStatus.GATHERING_CONTEXT)

        # STEP 1b — run context gathering
        # Runs on fresh start AND when resuming from GATHERING_CONTEXT after crash
        if job.status == JobStatus.GATHERING_CONTEXT:
            context_package = await self.run_step(
                job, db, JobStatus.GATHERING_CONTEXT,
                lambda: context_engineer.build(job)
            )
            if context_package.is_ambiguous:
                await self.transition(
                    db, job, JobStatus.AWAITING_CLARIFICATION,
                    context_package.clarification_needed,
                )
                return  # stops here — user must clarify before proceeding
            await self.transition(db, job, JobStatus.PLANNING, "Context gathered")

        # STEP 2 — Plan
        if job.status == JobStatus.PLANNING:
            # If server crashed and resumed here, context_package is None.
            # Re-gather it — reading JIRA + GitHub is fast and idempotent.
            if context_package is None:
                context_package = await context_engineer.build(job)

            await self.run_step(
                job, db, JobStatus.PLANNING,
                lambda: plan_job(job, context_package, db)
            )
            await self.transition(db, job, JobStatus.AWAITING_APPROVAL, "Plan ready for review")
            return  # hard stop — waits for human approval via REST API

        # STEP 3 — Execute (only reached after user clicks Approve)
        if job.status == JobStatus.EXECUTING:
            if context_package is None:
                context_package = await context_engineer.build(job)

            await self.run_step(
                job, db, JobStatus.EXECUTING,
                lambda: execute_code(job, context_package, db)
            )
            await self.transition(db, job, JobStatus.RAISING_PR, "Code written and committed")

        # STEP 4 — Raise PR
        if job.status == JobStatus.RAISING_PR:
            pr_url = await self.run_step(
                job, db, JobStatus.RAISING_PR,
                lambda: raise_pr(job, db)
            )
            job.pr_url = pr_url
            await db.commit()
            await self.transition(db, job, JobStatus.COMPLETED, f"PR raised: {pr_url}")

    # ------------------------------------------------------------------
    # Crash recovery — called once at app startup
    # ------------------------------------------------------------------

    async def resume_crashed_jobs(self) -> None:
        resumable = [
            s for s in JobStatus
            if s not in TERMINAL_STATES and s not in WAITING_STATES
        ]

        async with AsyncSessionFactory() as db:
            result = await db.execute(
                select(Job).where(Job.status.in_(resumable))
            )
            jobs = result.scalars().all()

        if not jobs:
            logger.info("No crashed jobs to resume")
            return

        for job in jobs:
            logger.info("Resuming job %s from state %s", job.id, job.status)
            asyncio.create_task(self.run_job(job.id))

    # ------------------------------------------------------------------
    # WebSocket emit (stub until Phase 4)
    # ------------------------------------------------------------------

    async def _emit(self, job_id: str, status: str, detail: str | None) -> None:
        if self.connection_manager is None:
            return
        await self.connection_manager.broadcast({
            "job_id": job_id,
            "status": status,
            "detail": detail,
        })


# ------------------------------------------------------------------
# Helper — decides if an error is worth retrying
# ------------------------------------------------------------------

def _is_retryable(exc: Exception) -> bool:
    retryable_signals = ("rate limit", "timeout", "503", "502", "529", "connection", "overloaded")
    return any(signal in str(exc).lower() for signal in retryable_signals)

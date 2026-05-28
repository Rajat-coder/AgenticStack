import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.harness import TERMINAL_STATES
from backend.db.models import Job, JobStatus
from backend.db.session import get_db
from backend.deps import harness
from backend.agent.orchestrator import revise_plan

router = APIRouter(prefix="/agent", tags=["agent"])


# ------------------------------------------------------------------
# Pydantic models — what the API accepts and returns
# ------------------------------------------------------------------

class StopRequest(BaseModel):
    reason: str | None = None

class ReviseRequest(BaseModel):
    feedback: str  # your instructions + answers to questions

class AssignRequest(BaseModel):
    ticket_id: str
    ticket_title: str


class JobResponse(BaseModel):
    job_id: str
    ticket_id: str
    status: str


class JobDetailResponse(BaseModel):
    job_id: str
    ticket_id: str
    ticket_title: str
    status: str
    plan: dict | None = None       # parsed from JSON — None until AWAITING_APPROVAL
    branch_name: str | None = None  # set after EXECUTING
    pr_url: str | None = None       # set after COMPLETED


# ------------------------------------------------------------------
# POST /agent/assign — create job and start harness
# ------------------------------------------------------------------

@router.post("/assign", status_code=201, response_model=JobResponse)
async def assign_ticket(
    body: AssignRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Assign a JIRA ticket to the agent.
    Creates a Job (QUEUED), returns immediately.
    Harness runs in background: QUEUED → PLANNING → AWAITING_APPROVAL.
    State changes arrive via WebSocket — not by polling this endpoint.
    """
    # Prevent duplicate active jobs for the same ticket
    active_statuses = [s for s in JobStatus if s not in TERMINAL_STATES]
    existing_result = await db.execute(
        select(Job)
        .where(Job.ticket_id == body.ticket_id)
        .where(Job.status.in_(active_statuses))
    )
    if existing_result.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"An active job already exists for ticket {body.ticket_id}",
        )

    job = Job(ticket_id=body.ticket_id, ticket_title=body.ticket_title)
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # BackgroundTasks: runs AFTER the HTTP response is sent.
    # The caller doesn't wait. Browser gets 201 in milliseconds.
    background_tasks.add_task(harness.run_job, job.id)

    return JobResponse(job_id=job.id, ticket_id=job.ticket_id, status=job.status.value)


# ------------------------------------------------------------------
# POST /agent/approve/{job_id} — user approves the plan
# ------------------------------------------------------------------

@router.post("/approve/{job_id}", response_model=JobResponse)
async def approve_plan(
    job_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    User approves the agent's plan. Code execution begins immediately.

    Critical ordering:
      1. transition(AWAITING_APPROVAL → EXECUTING) — commits to DB
      2. background_tasks.add_task(harness.run_job)
    Step 1 must finish before step 2 runs, or harness sees AWAITING_APPROVAL
    and skips (it's a WAITING_STATE).
    """
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.AWAITING_APPROVAL:
        raise HTTPException(
            status_code=409,
            detail=f"Job is '{job.status.value}' — can only approve AWAITING_APPROVAL jobs",
        )

    # Transition first, then schedule — order is critical
    await harness.transition(db, job, JobStatus.EXECUTING, "Plan approved by user")
    # NOTE: We do NOT mark the training example as "approved" here.
    # The example stays "pending" until the user reviews the actual PR code.
    # After reviewing: POST /finetuning/approve/{job_id} or /finetuning/reject/{job_id}
    background_tasks.add_task(harness.run_job, job.id)

    return JobResponse(job_id=job.id, ticket_id=job.ticket_id, status=job.status.value)

@router.post("/revise/{job_id}", response_model=JobDetailResponse)
async def revise_plan_endpoint(
    job_id: str,
    body: ReviseRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Give feedback on a plan before approving.
    LLM reads original context + original plan + your feedback → produces revised plan.
    Job stays at AWAITING_APPROVAL — then you approve or reject the revised plan.
    """
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.AWAITING_APPROVAL:
        raise HTTPException(
            status_code=409,
            detail=f"Job is '{job.status.value}' — can only revise AWAITING_APPROVAL jobs",
        )

    plan = await revise_plan(job, body.feedback, db)

    return JobDetailResponse(
        job_id=job.id,
        ticket_id=job.ticket_id,
        ticket_title=job.ticket_title,
        status=job.status.value,
        plan={
            "summary": plan.summary,
            "files_to_modify": plan.files_to_modify,
            "files_to_create": plan.files_to_create,
            "steps": plan.steps,
            "risk_level": plan.risk_level,
            "questions": plan.questions,
        },
        branch_name=job.branch_name,
        pr_url=job.pr_url,
    )


# ------------------------------------------------------------------
# POST /agent/stop/{job_id} — force any active job to FAILED
# ------------------------------------------------------------------

@router.post("/stop/{job_id}", response_model=JobResponse)
async def stop_job(
    job_id: str,
    body: StopRequest = StopRequest(),
    db: AsyncSession = Depends(get_db),
):
    """
    Stop a job immediately. Transitions to FAILED.
    Cannot stop jobs already in COMPLETED, FAILED, or TIMED_OUT.
    """
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status in TERMINAL_STATES:
        raise HTTPException(
            status_code=409,
            detail=f"Job is already in terminal state: {job.status.value}",
        )
    detail = f"Stopped by user: {body.reason}" if body.reason else "Stopped by user"
    await harness.transition(db, job, JobStatus.FAILED, detail)

    # Training example labeling is NOT done here anymore.
    # After stopping, use POST /finetuning/reject/{job_id} to label with a reason.
    # This keeps all labeling in one place — the /finetuning endpoints.
    return JobResponse(job_id=job.id, ticket_id=job.ticket_id, status=job.status.value)


# ------------------------------------------------------------------
# GET /agent/jobs — list all jobs (dashboard overview)
# ------------------------------------------------------------------

@router.get("/jobs", response_model=list[JobDetailResponse])
async def list_jobs(db: AsyncSession = Depends(get_db)):
    """List all jobs ordered by creation time, newest first."""
    result = await db.execute(select(Job).order_by(Job.created_at.desc()))
    jobs = result.scalars().all()

    return [
        JobDetailResponse(
            job_id=j.id,
            ticket_id=j.ticket_id,
            ticket_title=j.ticket_title,
            status=j.status.value,
            plan=json.loads(j.plan) if j.plan else None,
            branch_name=j.branch_name,
            pr_url=j.pr_url,
        )
        for j in jobs
    ]


# ------------------------------------------------------------------
# GET /agent/jobs/{job_id} — get one job with plan (approval screen)
# ------------------------------------------------------------------

@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get one job by ID. Includes the plan if it exists.
    The approval screen calls this to show the plan before the user clicks Approve.
    """
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobDetailResponse(
        job_id=job.id,
        ticket_id=job.ticket_id,
        ticket_title=job.ticket_title,
        status=job.status.value,
        plan=json.loads(job.plan) if job.plan else None,
        branch_name=job.branch_name,
        pr_url=job.pr_url,
    )
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.agent.finetuning import (
    get_example_counts,
    export_jsonl,
    get_finetune_status,
    start_finetune_job,
    update_example_label,
)
from backend.agent.search import store_job_embedding
from backend.db.models import Job
from backend.db.session import get_db
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

router = APIRouter(prefix="/finetuning", tags=["finetuning"])


class FinetuneJobResponse(BaseModel):
    job_id: str
    message: str


class PRFeedbackRequest(BaseModel):
    """
    Optional reason when rejecting after PR review.
    Be specific — this is what the LLM learns from.
    Example: "Executor added unnecessary imports and modified the wrong function"
    """
    reason: str | None = None


class FinetuneStatusResponse(BaseModel):
    job_id: str
    status: str
    model: str
    fine_tuned_model: str | None
    trained_tokens: int | None


@router.get("/examples")
async def get_example_count():
    """
    Shows count of training examples by status.
    Approved = used for fine-tuning (positive examples).
    Rejected = used for correction training (negative examples).
    Pending = plan generated but user hasn't acted yet.
    """
    counts = await get_example_counts()
    total_useful = counts["approved"] + counts["rejected"]
    return {
        "approved": counts["approved"],
        "rejected": counts["rejected"],
        "pending": counts["pending"],
        "total_useful": total_useful,
        "ready_to_finetune": counts["approved"] >= 1,
        "message": f"{total_useful} examples collected ({counts['approved']} approved, {counts['rejected']} rejected)",
    }


@router.post("/approve/{job_id}")
async def approve_example(job_id: str, db: AsyncSession = Depends(get_db)):
    # Mark as approved training example
    await update_example_label(job_id, "approved")
    
    # Store vector embedding — this job is now a "good example"
    # Future similar tickets will find this job and learn from it
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job and job.plan:
        import json
        plan_data = json.loads(job.plan)
        await store_job_embedding(job, plan_data.get("summary", ""))

    return {"job_id": job_id, "message": "Marked as approved. Embedding stored for vector search."}


@router.post("/reject/{job_id}")
async def reject_example(job_id: str, body: PRFeedbackRequest = PRFeedbackRequest()):
    """
    Call this AFTER reviewing the PR on GitHub and the code is wrong.
    Provide a specific reason — this is what the LLM learns from.

    Good reason: "Executor added extra imports not in the plan and modified auth.py which wasn't listed"
    Bad reason:  "wrong" (LLM learns nothing from this)
    """
    await update_example_label(job_id, "rejected", body.reason)
    return {"job_id": job_id, "message": "Marked as rejected. Reason saved for LLM learning."}


@router.post("/export")
async def export_examples():
    """
    Export all approved examples as a JSONL file.
    Returns the file path so you can review what will be sent to OpenAI.
    """
    try:
        file_path = await export_jsonl()
        return {"file_path": file_path, "message": "Export successful"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/start", response_model=FinetuneJobResponse)
async def start_finetuning():
    """
    Export examples and submit to OpenAI for fine-tuning.
    Returns a job_id — use GET /finetuning/status/{job_id} to check progress.
    Training takes 30-60 minutes on OpenAI's servers.
    """
    try:
        file_path = await export_jsonl()
        job_id = await start_finetune_job(file_path)
        return FinetuneJobResponse(
            job_id=job_id,
            message="Fine-tuning job started. Check status with GET /finetuning/status/{job_id}",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/status/{finetune_job_id}", response_model=FinetuneStatusResponse)
async def check_status(finetune_job_id: str):
    """
    Check the status of a fine-tuning job.
    When status = 'succeeded', fine_tuned_model contains your custom model ID.
    """
    try:
        result = await get_finetune_status(finetune_job_id)
        return FinetuneStatusResponse(
            job_id=result["job_id"],
            status=result["status"],
            model=result["model"],
            fine_tuned_model=result["fine_tuned_model"],
            trained_tokens=result["trained_tokens"],
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
import json
import logging
import os
import tempfile
from datetime import datetime, timezone

import openai
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.models import Job, TrainingExample
from backend.db.session import AsyncSessionFactory

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Save — called by orchestrator right after plan is generated
# ------------------------------------------------------------------

async def save_training_example(
    job: Job,
    system_prompt: str,
    user_content: str,
    assistant_content: str,
) -> None:
    """
    Save a training example with label='pending'.
    Label is updated to 'approved' when user clicks Approve,
    or 'rejected' when user clicks Stop.

    Why save at planning time (not approval time)?
    Because at approval time we no longer have the user_content
    (the context package is in memory during planning, not persisted separately).
    We save everything now, update the label later.
    """
    async with AsyncSessionFactory() as db:
        example = TrainingExample(
            job_id=job.id,
            system_prompt=system_prompt,
            user_content=user_content,
            assistant_content=assistant_content,
            label="pending",
        )
        db.add(example)
        await db.commit()
        logger.info("Training example saved for job %s", job.id)


async def update_example_label(job_id: str, label: str, rejection_reason: str | None = None) -> None:
    """
    Update label to 'approved' or 'rejected'.
    rejection_reason is stored when label = 'rejected' — used in training
    to teach the LLM what it did wrong and what it should have done instead.
    """
    async with AsyncSessionFactory() as db:
        result = await db.execute(
            select(TrainingExample)
            .where(TrainingExample.job_id == job_id)
            .order_by(TrainingExample.created_at.desc())
            .limit(1)
        )
        example = result.scalar_one_or_none()
        if example:
            example.label = label
            if rejection_reason:
                example.rejection_reason = rejection_reason
            await db.commit()
            logger.info("Training example for job %s → %s | reason: %s", job_id, label, rejection_reason)


# ------------------------------------------------------------------
# Count — how many approved examples exist
# ------------------------------------------------------------------

async def get_example_counts() -> dict:
    """Returns count of examples by label — pending, approved, rejected."""
    async with AsyncSessionFactory() as db:
        result = await db.execute(
            select(TrainingExample.label, func.count().label("count"))
            .group_by(TrainingExample.label)
        )
        rows = result.all()

    counts = {"pending": 0, "approved": 0, "rejected": 0}
    for label, count in rows:
        counts[label] = count
    return counts


# ------------------------------------------------------------------
# Export — convert approved examples to JSONL file
# ------------------------------------------------------------------

async def export_jsonl() -> str:
    """
    Export all approved training examples as a JSONL file.
    Each line is one JSON object in OpenAI's fine-tuning format:
    {"messages": [{"role": "system", ...}, {"role": "user", ...}, {"role": "assistant", ...}]}

    Returns the file path of the exported JSONL.
    """
    async with AsyncSessionFactory() as db:
        result = await db.execute(
            select(TrainingExample)
            .where(TrainingExample.label.in_(["approved", "rejected"]))
            .order_by(TrainingExample.created_at.asc())
        )
        examples = result.scalars().all()
    

    if not examples:
        raise ValueError("No approved training examples to export")

    # Write to a temp file — OpenAI upload needs a real file path
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    export_dir = "/tmp/agentictask_exports"
    os.makedirs(export_dir, exist_ok=True)
    file_path = f"{export_dir}/training_{timestamp}.jsonl"

    with open(file_path, "w", encoding="utf-8") as f:
        for example in examples:
            if example.label == "approved":
                # Positive example — LLM learns "do this"
                line = {
                    "messages": [
                        {"role": "system",    "content": example.system_prompt},
                        {"role": "user",      "content": example.user_content},
                        {"role": "assistant", "content": example.assistant_content},
                    ]
                }
            else:
                # Negative example with correction — LLM learns "don't do this, do this instead"
                # The rejection_reason tells the LLM exactly what was wrong
                # Only include if rejection reason was provided — otherwise skip
                if not example.rejection_reason:
                    continue
                line = {
                    "messages": [
                        {"role": "system",    "content": example.system_prompt},
                        {"role": "user",      "content": example.user_content},
                        {"role": "assistant", "content": example.assistant_content},
                        {"role": "user",      "content": f"FEEDBACK: This plan was rejected. Reason: {example.rejection_reason}. Remember this for similar tickets in future."},
                    ]
                }
            f.write(json.dumps(line) + "\n")

    logger.info("Exported %d examples to %s", len(examples), file_path)
    return file_path


# ------------------------------------------------------------------
# Submit — upload JSONL to OpenAI and start fine-tuning
# ------------------------------------------------------------------

async def start_finetune_job(file_path: str) -> str:
    """
    Upload the JSONL file to OpenAI and start a fine-tuning job.
    Returns the fine-tuning job ID (used to check status later).

    The fine-tuning job runs asynchronously on OpenAI's servers.
    It takes 30-60 minutes. Use get_finetune_status() to poll.
    """
    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)

    # Step 1 — upload the file
    with open(file_path, "rb") as f:
        upload_response = await client.files.create(
            file=f,
            purpose="fine-tune",
        )
    file_id = upload_response.id
    logger.info("File uploaded to OpenAI: %s", file_id)

    # Step 2 — create fine-tuning job
    # gpt-4o-mini is the recommended model for fine-tuning — cheaper than gpt-4o
    # and fine-tuned mini often outperforms base gpt-4o on domain-specific tasks
    job_response = await client.fine_tuning.jobs.create(
        training_file=file_id,
        model="gpt-4o-mini-2024-07-18",
    )
    job_id = job_response.id
    logger.info("Fine-tuning job started: %s", job_id)

    return job_id


async def get_finetune_status(finetune_job_id: str) -> dict:
    """
    Check the status of a fine-tuning job.
    Returns status and fine_tuned_model ID when complete.

    Possible statuses: validating_files, queued, running, succeeded, failed, cancelled
    When status = "succeeded", fine_tuned_model contains the custom model ID.
    Use that model ID in planner.py / executor.py to switch to your custom model.
    """
    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    job = await client.fine_tuning.jobs.retrieve(finetune_job_id)

    return {
        "job_id": job.id,
        "status": job.status,
        "model": job.model,
        "fine_tuned_model": job.fine_tuned_model,  # None until succeeded
        "trained_tokens": job.trained_tokens,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
    }

async def get_example_by_job(job_id: str) -> TrainingExample | None:
    """
    Fetch the training example for a job.
    Used by revise_plan() — we stored the original context here
    at planning time, so we don't need to re-gather it.
    """
    async with AsyncSessionFactory() as db:
        result = await db.execute(
            select(TrainingExample)
            .where(TrainingExample.job_id == job_id)
            .order_by(TrainingExample.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
import json
import logging
from backend.config import settings
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.context import ContextPackage
from backend.agent.executor import execute_plan
from backend.agent.finetuning import save_training_example, get_example_by_job
from backend.agent.planner import AgentPlan, generate_plan, _load_system_prompt
from backend.db.models import Job
from backend.integrations.github import github
from backend.integrations.jira import jira
from backend.agent.search import find_similar_jobs, format_similar_jobs_for_context, store_job_embedding

logger = logging.getLogger(__name__)


async def plan_job(job: Job, context: ContextPackage, db: AsyncSession) -> AgentPlan:
    """
    Called by harness in PLANNING state.xx
    Runs the planner LLM call, serializes result to DB, returns the plan.
    Harness transitions to AWAITING_APPROVAL after this returns.
    """
    ticket_text = f"{job.ticket_title} {context.ticket.description}"
    similar = await find_similar_jobs(ticket_text)
    context.similar_jobs_context = format_similar_jobs_for_context(similar)
    

    if similar:
        logger.info("Injecting %d similar past jobs into planner context", len(similar))
    plan = await generate_plan(context)
    system_prompt, _, _, _ = await _load_system_prompt("planner")
    await save_training_example(
        job=job,
        system_prompt=system_prompt,
        user_content=context.to_prompt_string(),
        assistant_content=json.dumps({
            "summary": plan.summary,
            "files_to_modify": plan.files_to_modify,
            "files_to_create": plan.files_to_create,
            "steps": plan.steps,
            "risk_level": plan.risk_level,
            "questions": plan.questions,
        }),
    )

    # Serialize to JSON so it survives server restarts (job.plan is a TEXT column)
    job.plan = json.dumps({
        "summary": plan.summary,
        "files_to_modify": plan.files_to_modify,
        "files_to_create": plan.files_to_create,
        "steps": plan.steps,
        "risk_level": plan.risk_level,
        "questions": plan.questions,
    })
    await db.commit()

    return plan

async def revise_plan(job: Job, feedback: str, db: AsyncSession) -> AgentPlan:
    """
    Called when user gives feedback on a plan before approving.
    Reuses original context from training_examples table — no need to
    re-gather from JIRA/GitHub/codebase.

    Revision prompt = original context + original plan + user feedback.
    LLM reads all three and produces an improved plan.
    """
    from backend.agent.planner import _call_anthropic, _call_openai, _call_ollama, _parse_plan

    # Load original context and plan from training example
    example = await get_example_by_job(str(job.id))
    if not example:
        raise ValueError("No training example found for this job — cannot revise")

    system_prompt, temperature, max_tokens, top_p = await _load_system_prompt("planner")

    # Build revision message — original context + original plan + feedback
    revision_message = f"""{example.user_content}

            ## Original Plan (needs revision)
            {example.assistant_content}

            ## User Feedback
            {feedback}

            Revise the plan based on the feedback above.
            Return the same JSON format — no text outside the JSON."""

    logger.info("Revising plan for job %s | feedback: %s", job.id, feedback[:100])

    if settings.ai_provider == "anthropic":
        raw = await _call_anthropic(system_prompt, revision_message, temperature, max_tokens, top_p)
    elif settings.ai_provider == "ollama":
        raw = await _call_ollama(system_prompt, revision_message, temperature, max_tokens, top_p)
    else:
        raw = await _call_openai(system_prompt, revision_message, temperature, max_tokens, top_p)

    plan = _parse_plan(raw)

    # Update plan in DB — job stays AWAITING_APPROVAL
    job.plan = json.dumps({
        "summary": plan.summary,
        "files_to_modify": plan.files_to_modify,
        "files_to_create": plan.files_to_create,
        "steps": plan.steps,
        "risk_level": plan.risk_level,
        "questions": plan.questions,
    })

    # Update training example with revised plan
    if example:
        example.assistant_content = job.plan
    
    await db.commit()
    logger.info("Plan revised for job %s", job.id)
    return plan


async def execute_code(job: Job, context: ContextPackage, db: AsyncSession) -> None:
    """
    Called by harness in EXECUTING state.
    Deserializes plan from DB, writes code, commits, saves branch_name.
    Does NOT raise the PR — crash boundary sits between commit and PR.
    """
    plan_data = json.loads(job.plan)
    plan = AgentPlan(**plan_data)

    result = await execute_plan(job, plan, context)

    # Save branch_name before this step ends — raise_pr needs it even after a crash
    job.branch_name = result.branch_name
    await db.commit()


async def raise_pr(job: Job, db: AsyncSession) -> str:
    """
    Called by harness in RAISING_PR state.
    Reads branch_name from DB (written by execute_code).
    Opens GitHub PR, updates JIRA status, returns PR URL.
    """
    plan_data = json.loads(job.plan)
    plan = AgentPlan(**plan_data)

    pr_title = f"[{job.ticket_id}] {job.ticket_title}"
    pr_body = _build_pr_body(job, plan)

    pr_url = await github.create_pr(
        title=pr_title,
        body=pr_body,
        head_branch=job.branch_name,
    )

    try:
        await jira.update_status(job.ticket_id, "In Review")
    except Exception as exc:
        logger.warning("Could not update JIRA status: %s", exc)

    logger.info("PR raised: %s | JIRA %s → In Review", pr_url, job.ticket_id)
    return pr_url


def _build_pr_body(job: Job, plan: AgentPlan) -> str:
    lines = [
        "## Summary",
        plan.summary,
        "",
        "## Changes",
    ]
    for f in plan.files_to_modify:
        lines.append(f"- Modified: `{f}`")
    for f in plan.files_to_create:
        lines.append(f"- Created: `{f}`")
    lines += [
        "",
        "## Steps Implemented",
    ]
    for i, step in enumerate(plan.steps, 1):
        lines.append(f"{i}. {step}")
    lines += [
        "",
        f"## Risk Level: {plan.risk_level.upper()}",
        "",
        "---",
        f"JIRA: {job.ticket_id}",
        f"Branch: `{job.branch_name}`",
        "*Auto-generated by AgenticTask*",
    ]
    return "\n".join(lines)
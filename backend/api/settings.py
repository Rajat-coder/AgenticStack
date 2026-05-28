from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import PromptConfig
from backend.db.session import get_db

router = APIRouter(prefix="/settings", tags=["settings"])


# ------------------------------------------------------------------
# Pydantic models
# ------------------------------------------------------------------

class PromptResponse(BaseModel):
    id: str
    step: str
    system_prompt: str
    custom_rules: str
    version: int
    temperature: float
    max_tokens: int
    top_p: float


class UpdatePromptRequest(BaseModel):
    system_prompt: str
    custom_rules: str = ""
    temperature: float = 0.4
    max_tokens: int = 2048
    top_p: float = 1.0


# ------------------------------------------------------------------
# GET /settings/prompt/{step} — read active prompt
# ------------------------------------------------------------------

@router.get("/prompt/{step}", response_model=PromptResponse)
async def get_prompt(step: str, db: AsyncSession = Depends(get_db)):
    """
    Read the active system prompt for a step.
    step = "planner" or "executor"

    Returns the highest version where is_active = True.
    """
    result = await db.execute(
        select(PromptConfig)
        .where(PromptConfig.step == step)
        .where(PromptConfig.is_active == True)
        .order_by(PromptConfig.version.desc())
        .limit(1)
    )
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=404,
            detail=f"No active prompt found for step '{step}'. Valid steps: planner, executor"
        )

    return PromptResponse(
        id=config.id,
        step=config.step,
        system_prompt=config.system_prompt,
        custom_rules=config.custom_rules,
        version=config.version,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        top_p=config.top_p,
    )

# ------------------------------------------------------------------
# PUT /settings/prompt/{step} — update prompt (creates new version)
# ------------------------------------------------------------------

@router.put("/prompt/{step}", response_model=PromptResponse)
async def update_prompt(
    step: str,
    body: UpdatePromptRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Update the system prompt for a step.

    Does NOT overwrite — creates a new version and deactivates all old ones.
    This preserves full version history and allows rollback.

    Changes take effect on the next job run. No server restart needed.
    """
    # Find the latest version so we know what number comes next
    result = await db.execute(
        select(PromptConfig)
        .where(PromptConfig.step == step)
        .order_by(PromptConfig.version.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none()
    next_version = (latest.version + 1) if latest else 1

    # Deactivate all existing versions for this step
    all_result = await db.execute(
        select(PromptConfig).where(PromptConfig.step == step)
    )
    for config in all_result.scalars().all():
        config.is_active = False

    # Create the new active version
    new_config = PromptConfig(
        step=step,
        system_prompt=body.system_prompt,
        custom_rules=body.custom_rules,
        version=next_version,
        is_active=True,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        top_p=body.top_p,
    )
    db.add(new_config)
    await db.commit()
    await db.refresh(new_config)

    return PromptResponse(
        id=config.id,
        step=config.step,
        system_prompt=config.system_prompt,
        custom_rules=config.custom_rules,
        version=config.version,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        top_p=config.top_p,
    )
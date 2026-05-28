import json
import logging
from dataclasses import dataclass, field

import anthropic
import openai
from sqlalchemy import select

from backend.agent.context import ContextPackage
from backend.config import settings
from backend.db.models import PromptConfig
from backend.db.session import AsyncSessionFactory

logger = logging.getLogger(__name__)


@dataclass
class AgentPlan:
    """
    Structured plan returned by the LLM.
    Shown to the user in the dashboard for approval.
    """
    summary: str
    files_to_modify: list[str] = field(default_factory=list)
    files_to_create: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    risk_level: str = "medium"
    questions: list[str] = field(default_factory=list)

    def to_readable(self) -> str:
        """Human-readable format shown in the dashboard."""
        lines = [
            f"## Summary\n{self.summary}",
            f"\n## Risk Level: {self.risk_level.upper()}",
        ]
        if self.files_to_modify:
            lines.append("\n## Files to Modify")
            for f in self.files_to_modify:
                lines.append(f"  - {f}")
        if self.files_to_create:
            lines.append("\n## Files to Create")
            for f in self.files_to_create:
                lines.append(f"  - {f}")
        if self.steps:
            lines.append("\n## Steps")
            for i, step in enumerate(self.steps, 1):
                lines.append(f"  {i}. {step}")
        if self.questions:
            lines.append("\n## Questions")
            for q in self.questions:
                lines.append(f"  - {q}")
        return "\n".join(lines)


# ------------------------------------------------------------------
# Main entry point — called by harness during PLANNING step
# ------------------------------------------------------------------

async def generate_plan(context: ContextPackage) -> AgentPlan:
    """
    1. Load system prompt from DB
    2. Build user message from context package
    3. Call LLM (Anthropic or OpenAI based on config)
    4. Parse JSON response into AgentPlan
    """
    system_prompt, temperature, max_tokens, top_p = await _load_system_prompt("planner")
    user_message = context.to_prompt_string() + """

            ## Required Output Format
            Return a JSON object with exactly these keys — no other text outside the JSON:
            {
            "summary": "one paragraph describing what needs to change and why",
            "files_to_modify": ["existing file paths that need to be changed"],
            "files_to_create": ["new file paths that need to be created"],
            "steps": ["ordered list of concrete implementation steps"],
            "risk_level": "low or medium or high",
            "questions": ["any questions if something is unclear, otherwise empty list"]
            }"""

    logger.info(
        "Calling %s for planning | ~%d input tokens",
        settings.ai_provider,
        context.token_count,
    )

    if settings.ai_provider == "anthropic":
        raw = await _call_anthropic(system_prompt, user_message, temperature, max_tokens, top_p)
    elif settings.ai_provider == "ollama":
        raw = await _call_ollama(system_prompt, user_message, temperature, max_tokens, top_p)
    else:
        raw = await _call_openai(system_prompt, user_message, temperature, max_tokens, top_p)

    plan = _parse_plan(raw)

    logger.info(
        "Plan ready | risk=%s | modify=%d | create=%d | steps=%d | questions=%d",
        plan.risk_level,
        len(plan.files_to_modify),
        len(plan.files_to_create),
        len(plan.steps),
        len(plan.questions),
    )
    return plan


# ------------------------------------------------------------------
# Load system prompt from DB
# ------------------------------------------------------------------

async def _load_system_prompt(step: str) -> tuple[str, float, int, float]:
    """
    Returns (system_prompt, temperature, max_tokens, top_p) from DB.
    All 4 are needed to make the LLM call — loading them together is cleaner
    than making two separate DB calls.
    """
    async with AsyncSessionFactory() as db:
        result = await db.execute(
            select(PromptConfig).where(
                PromptConfig.step == step,
                PromptConfig.is_active == True,
            )
        )
        config = result.scalar_one_or_none()

    if config is None:
        logger.warning("No prompt config for step '%s' — using fallback", step)
        return "You are a senior software engineer. Return valid JSON only.", 0.4, 2048, 1.0

    prompt = config.system_prompt
    if config.custom_rules:
        prompt += f"\n\nAdditional project rules:\n{config.custom_rules}"

    return prompt, config.temperature, config.max_tokens, config.top_p


# ------------------------------------------------------------------
# LLM API calls
# ------------------------------------------------------------------

async def _call_anthropic(system_prompt: str, user_message: str, temperature: float = 0.4, max_tokens: int = 2048, top_p: float = 1.0) -> str:
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model="claude-opus-4-5",
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_prompt,
        top_p=top_p, 
        messages=[
            {"role": "user", "content": user_message}
        ],
    )
    # content is a list — [0] is the first (and only) text block
    return message.content[0].text

async def _call_ollama(system_prompt: str, user_message: str, temperature: float = 0.4, max_tokens: int = 2048, top_p: float = 1.0) -> str:
    client = openai.AsyncOpenAI(
        base_url=settings.ollama_base_url,
        api_key="ollama",               
    )
    response = await client.chat.completions.create(
        model=settings.ollama_model,        
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ],
    )
    return response.choices[0].message.content


async def _call_openai(system_prompt: str, user_message: str, temperature: float = 0.4, max_tokens: int = 2048, top_p: float = 1.0) -> str:
    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model="gpt-4o",
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ],
    )
    return response.choices[0].message.content


# ------------------------------------------------------------------
# Parse LLM response → AgentPlan
# ------------------------------------------------------------------

def _parse_plan(raw: str) -> AgentPlan:
    """
    LLMs return JSON but sometimes wrap it in markdown code fences:

        ```json
        {"summary": "..."}
        ```

    We strip those first, then parse.
    If parsing fails entirely — return a safe fallback plan.
    Never crash the job over a JSON parse error.
    """
    cleaned = raw.strip()

    # Strip markdown code fences if present
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1]).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error(
            "LLM returned invalid JSON: %s\nFirst 500 chars: %s",
            exc, raw[:500]
        )
        # Return a fallback — human will see it in dashboard and can retry
        return AgentPlan(
            summary="Could not parse LLM response. Please retry or review manually.",
            risk_level="high",
            questions=["LLM returned invalid JSON — manual review required"],
        )

    return AgentPlan(
        summary=data.get("summary", ""),
        files_to_modify=data.get("files_to_modify", []),
        files_to_create=data.get("files_to_create", []),
        steps=data.get("steps", []),
        risk_level=data.get("risk_level", "medium"),
        questions=data.get("questions", []),
    )
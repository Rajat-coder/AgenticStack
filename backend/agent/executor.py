import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import anthropic
import openai

from backend.agent.context import ContextPackage
from backend.agent.planner import AgentPlan, _load_system_prompt
from backend.config import settings
from backend.db.models import Job

logger = logging.getLogger(__name__)


@dataclass
class FileChange:
    file_path: str
    content: str = ""     
    find: str = ""     
    replace: str = ""   
    is_new_file: bool = False


@dataclass
class ExecutionResult:
    changes: list[FileChange] = field(default_factory=list)
    commit_sha: str = ""
    commit_message: str = ""
    branch_name: str = ""


# ------------------------------------------------------------------
# Main entry point — called by harness during EXECUTING step
# ------------------------------------------------------------------

async def execute_plan(
    job: Job,
    plan: AgentPlan,
    context: ContextPackage,
) -> ExecutionResult:
    """
    1. Create or checkout the feature branch
    2. Call LLM to write the actual code
    3. Write files to disk
    4. Git add + commit
    5. Return result with commit SHA and branch name
    """
    repo_path = Path(settings.target_repo_path)
    branch_name = _build_branch_name(job.ticket_id, plan.summary)

    # Step 1 — Set up git branch on local repo
    _setup_branch(repo_path, branch_name)
    logger.info("On branch %s", branch_name)

    # Step 2 — Call LLM to write code
    system_prompt, temperature, max_tokens, top_p = await _load_system_prompt("executor")
    user_message = _build_executor_prompt(plan, context)

    logger.info(
        "Calling %s for execution | %d plan steps",
        settings.ai_provider, len(plan.steps)
    )

    if settings.ai_provider == "anthropic":
        raw = await _call_anthropic(system_prompt, user_message, temperature, max_tokens, top_p)
    elif settings.ai_provider == "ollama":
        raw = await _call_ollama(system_prompt, user_message, temperature, max_tokens, top_p)
    else:
        raw = await _call_openai(system_prompt, user_message, temperature, max_tokens, top_p)
    # Step 3 — Parse LLM response into file changes
    result = _parse_execution(raw)
    result.branch_name = branch_name

    # Step 4 — Write every file to disk
    for change in result.changes:
        _write_file(repo_path, change)
        logger.info("Written: %s", change.file_path)

    # Step 5 — Git commit all changes
    commit_message = (
        result.commit_message
        or f"[{job.ticket_id}] {plan.summary[:60]}"
    )
    sha = _git_commit(repo_path, commit_message, [c.file_path for c in result.changes])
    _git_push(repo_path, branch_name) 
    result.commit_sha = sha
    result.commit_message = commit_message

    logger.info(
        "Execution done | branch=%s | files=%d | sha=%s",
        branch_name, len(result.changes), sha
    )
    return result


# ------------------------------------------------------------------
# Build the prompt for the executor LLM call
# ------------------------------------------------------------------

def _build_executor_prompt(plan: AgentPlan, context: ContextPackage) -> str:
    """
    Combine the approved plan + full context into one prompt.
    The LLM must implement exactly what the plan says.
    """
    parts = []

    parts.append("## Approved Plan")
    parts.append(plan.to_readable())

    parts.append("\n## Context")
    parts.append(context.to_prompt_string())

    parts.append("\n## Instructions")
    parts.append(
        "Implement the approved plan exactly as described.\n"
        "Return a JSON object in this format:\n"
        "{\n"
        '  "changes": [\n'
        '    {\n'
        '      "file_path": "relative/path/to/existing_file.py",\n'
        '      "find": "exact block of existing code to replace — must match the file exactly",\n'
        '      "replace": "new code to put in its place"\n'
        '    }\n'
        "  ],\n"
        '  "new_files": [\n'
        '    {"file_path": "relative/path/to/new_file.py", "content": "full file content"}\n'
        "  ],\n"
        '  "commit_message": "[TICKET-ID] short description"\n'
        "}\n\n"
        "Rules:\n"
        "- For EXISTING files: use changes[] with find/replace only\n"
        "- The find string must match EXACTLY what is in the current file shown above\n"
        "- For NEW files: use new_files[] with full content\n"
        "- Only change what the plan specifies — nothing else\n"
        "- Follow existing code style exactly\n"
        "- Return ONLY the JSON — no explanation outside it"
    )

    return "\n\n".join(parts)


# ------------------------------------------------------------------
# LLM calls — same pattern as planner but lower temperature
# ------------------------------------------------------------------

async def _call_anthropic(system_prompt: str, user_message: str, temperature: float = 0.1, max_tokens: int = 4096, top_p: float = 1.0) -> str:
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model="claude-opus-4-5",
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return message.content[0].text

async def _call_ollama(system_prompt: str, user_message: str, temperature: float = 0.1, max_tokens: int = 4096, top_p: float = 1.0) -> str:
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


async def _call_openai(system_prompt: str, user_message: str, temperature: float = 0.1, max_tokens: int = 4096, top_p: float = 1.0) -> str:
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
# Parse LLM response
# ------------------------------------------------------------------

def _parse_execution(raw: str) -> ExecutionResult:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1]).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error("Executor LLM returned invalid JSON: %s", exc)
        return ExecutionResult()

    changes = []

    for c in data.get("changes", []):
        changes.append(FileChange(
            file_path=c["file_path"],
            find=c.get("find", ""),
            replace=c.get("replace", ""),
            is_new_file=False,
        ))

    for c in data.get("new_files", []):
        changes.append(FileChange(
            file_path=c["file_path"],
            content=c.get("content", ""),
            is_new_file=True,
        ))

    return ExecutionResult(
        changes=changes,
        commit_message=data.get("commit_message", ""),
    )


# ------------------------------------------------------------------
# File and git operations
# ------------------------------------------------------------------

def _write_file(repo_path: Path, change: FileChange) -> bool:
    full_path = repo_path / change.file_path

    if change.is_new_file:
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(change.content, encoding="utf-8")
        return True

    if not full_path.exists():
        logger.warning("File %s not found — skipping", change.file_path)
        return False

    current = full_path.read_text(encoding="utf-8")

    if change.find not in current:
        logger.warning("find string not found in %s — skipping", change.file_path)
        return False

    updated = current.replace(change.find, change.replace, 1)
    full_path.write_text(updated, encoding="utf-8")
    return True


def _setup_branch(repo_path: Path, branch_name: str) -> None:
    """
    If branch already exists → check it out (resume after crash).
    If not → create it from main.
    """
    # Check if branch exists locally
    result = subprocess.run(
        ["git", "branch", "--list", branch_name],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    branch_exists = bool(result.stdout.strip())

    if branch_exists:
        subprocess.run(
            ["git", "checkout", branch_name],
            cwd=repo_path, check=True
        )
        logger.info("Checked out existing branch %s", branch_name)
    else:
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=repo_path, check=True
        )
        subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=repo_path, check=True
        )
        logger.info("Created new branch %s from main", branch_name)


def _git_commit(repo_path: Path, message: str, file_paths: list[str]) -> str:
    """
    Stage only the files the agent wrote and commit.
    Returns the commit SHA.
    """
    for path in file_paths:
        subprocess.run(
            ["git", "add", path],
            cwd=repo_path, check=True
        )

    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo_path, check=True
    )

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()[:7]

def _git_push(repo_path: Path, branch_name: str) -> None:
    subprocess.run(
        ["git", "push", "-u", "origin", branch_name],
        cwd=repo_path, check=True
    )


def _build_branch_name(ticket_id: str, summary: str) -> str:
    """
    Build branch name from ticket ID and plan summary.
    Example: agentictask/AT-42-fix-login-bug
    """
    slug = summary[:40].lower()
    slug = re.sub(r'[^a-z0-9]+', '-', slug).strip('-')
    return f"agentictask/{ticket_id}-{slug}"
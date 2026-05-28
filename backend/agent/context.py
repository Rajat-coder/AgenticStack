import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import tiktoken

from backend.config import settings
from backend.db.models import Job
from backend.integrations.github import Commit, PullRequest, github
from backend.integrations.jira import JiraTicket, jira

logger = logging.getLogger(__name__)

# Maximum tokens we send to the LLM as context.
# Leaves room for system prompt + LLM output on the other side.
MAX_CONTEXT_TOKENS = 8_000

# cl100k_base is the encoding used by GPT-4 and a close approximation for Claude.
# tiktoken gives us exact token counts before we send anything.
ENCODING = tiktoken.get_encoding("cl100k_base")


@dataclass
class ContextPackage:
    """
    Everything the agent needs before it starts thinking.
    Built by ContextEngineer, consumed by the orchestrator (Phase 3).
    """
    ticket: JiraTicket
    codebase_sections: list[str] = field(default_factory=list)
    actual_file_contents: list[str] = field(default_factory=list)
    recent_commits: list[Commit] = field(default_factory=list)
    conflicting_prs: list[PullRequest] = field(default_factory=list)
    token_count: int = 0
    is_ambiguous: bool = False
    clarification_needed: str | None = None
    similar_jobs_context: str = ""

    def to_prompt_string(self) -> str:
        """
        Formats the entire context package as a single string
        ready to be injected into the LLM prompt.
        """
        parts = []
        if self.similar_jobs_context:
            parts.append(self.similar_jobs_context)
        parts.append(f"## JIRA Ticket: {self.ticket.ticket_id}")
        parts.append(f"Title: {self.ticket.title}")
        parts.append(f"Description:\n{self.ticket.description}")

        if self.ticket.acceptance_criteria:
            parts.append(f"Acceptance Criteria:\n{self.ticket.acceptance_criteria}")

        if self.recent_commits:
            parts.append("## Recent Commits on main")
            for c in self.recent_commits:
                parts.append(f"- {c.sha} | {c.date[:10]} | {c.author}: {c.message}")

        if self.conflicting_prs:
            parts.append("## WARNING — Open PRs That May Conflict")
            for pr in self.conflicting_prs:
                files = ", ".join(pr.changed_files[:5])
                parts.append(f"- PR #{pr.number}: {pr.title} — touches: {files}")

        if self.codebase_sections:
            parts.append("## Relevant Codebase Sections")
            for section in self.codebase_sections:
                parts.append(section)
        
        if self.actual_file_contents:                  
            parts.append("## Actual File Contents")
            for file_content in self.actual_file_contents:
                parts.append(file_content)

        return "\n\n".join(parts)


class ContextEngineer:

    async def build(self, job: Job) -> ContextPackage:
        """
        Main entry point — called by the harness during GATHERING_CONTEXT.
        Returns a focused ContextPackage the planner can work with immediately.
        """
        logger.info("Building context for ticket %s", job.ticket_id)

        # Step 1 — Read the JIRA ticket
        ticket = await jira.get_ticket(job.ticket_id)

        # Step 2 — Read recent GitHub activity
        commits = await github.get_recent_commits(limit=10)
        open_prs = await github.get_open_prs()

        # Step 3 — Extract keywords from the ticket
        keywords = _extract_keywords(ticket.title + " " + ticket.description)

        # Step 4 — Read AgenticStack.txt and keep only relevant sections
        codebase_sections = self._extract_relevant_sections(ticket, keywords)

        actual_files = self._read_relevant_files(codebase_sections)

        # Step 5 — Flag any open PRs that likely touch the same files
        conflicting_prs = _detect_conflicts(open_prs, keywords)

        # Step 6 — Check if the ticket is too vague to proceed
        is_ambiguous, clarification = _check_ambiguity(ticket)

        # Step 7 — Assemble and measure
        package = ContextPackage(
            ticket=ticket,
            codebase_sections=codebase_sections,
            recent_commits=commits,
            actual_file_contents=actual_files, 
            conflicting_prs=conflicting_prs,
            is_ambiguous=is_ambiguous,
            clarification_needed=clarification,
        )
        package.token_count = _count_tokens(package.to_prompt_string())

        logger.info(
            "Context ready — ticket=%s | tokens=%d | sections=%d | conflicts=%d | ambiguous=%s",
            job.ticket_id,
            package.token_count,
            len(codebase_sections),
            len(conflicting_prs),
            is_ambiguous,
        )

        return package

    def _extract_relevant_sections(
        self, ticket: JiraTicket, keywords: set[str]
    ) -> list[str]:
        """
        This is the RAG retrieval step.

        1. Load AgenticStack.txt from the target repo
        2. Split it into sections
        3. Score each section by keyword overlap with the ticket
        4. Return top sections that fit within the token budget
        """
        stack_file = Path(settings.target_repo_path) / "AgenticStack.txt"

        if not stack_file.exists():
            logger.warning("AgenticStack.txt not found at %s", stack_file)
            return []

        raw = stack_file.read_text(encoding="utf-8")
        sections = _split_into_sections(raw)

        # Score every section
        scored = [
            (section, _score_section(section, keywords))
            for section in sections
        ]

        # Sort highest relevance first
        scored.sort(key=lambda x: x[1], reverse=True)

        # Fill up to half the token budget with codebase sections.
        # The other half is reserved for ticket details, commits, and LLM output.
        budget = MAX_CONTEXT_TOKENS // 2
        selected = []
        used_tokens = 0

        for section, score in scored:
            if score == 0:
                break  # everything from here has zero relevance — stop

            section_tokens = _count_tokens(section)
            if used_tokens + section_tokens > budget:
                break  # would exceed budget — stop

            selected.append(section)
            used_tokens += section_tokens

        logger.info(
            "AgenticStack: selected %d/%d sections using %d tokens",
            len(selected), len(sections), used_tokens,
        )
        return selected
    
    def _read_relevant_files(self, sections: list[str]) -> list[str]:
        """
        From the relevant AgenticStack.txt sections, extract file paths.
        Read those actual files from the target repo.
        Send real code — not just the map.

        Token budget: whatever is left after codebase sections used their half.
        We use a quarter of MAX_CONTEXT_TOKENS for actual files.
        """
        base_path = Path(settings.target_repo_path)
        if not base_path.exists():
            return []

        file_paths = _extract_file_paths("\n".join(sections))
        if not file_paths:
            return []

        budget = MAX_CONTEXT_TOKENS // 4  # quarter of total budget for actual files
        contents = []
        used_tokens = 0

        for relative_path in file_paths:
            full_path = base_path / relative_path
            if not full_path.exists():
                continue

            try:
                code = full_path.read_text(encoding="utf-8")
                formatted = f"### {relative_path}\n```\n{code}\n```"
                tokens = _count_tokens(formatted)

                if used_tokens + tokens > budget:
                    logger.info("File %s skipped — would exceed file budget", relative_path)
                    continue

                contents.append(formatted)
                used_tokens += tokens
                logger.info("Included file %s (%d tokens)", relative_path, tokens)

            except Exception as exc:
                logger.warning("Could not read file %s: %s", relative_path, exc)

        return contents
    


# ------------------------------------------------------------------
# Pure helper functions — no side effects, easy to test
# ------------------------------------------------------------------

def _extract_file_paths(text: str) -> list[str]:
    """
    Extract file paths mentioned in AgenticStack.txt sections.
    Looks for patterns like: backend/auth.py, src/models/user.py
    """
    pattern = re.compile(r'\b([\w/\\]+\.(py|js|ts|jsx|tsx|json|yaml|yml|md))\b')
    matches = pattern.findall(text)
    seen = set()
    result = []
    for match, _ in matches:
        if match not in seen and not match.startswith("."):
            seen.add(match)
            result.append(match)
    return result

def _split_into_sections(text: str) -> list[str]:
    """
    Split AgenticStack.txt into sections by markdown headers.
    Each section starts with # ## or ###
    """
    sections = re.split(r'\n(?=#{1,3} )', text)
    return [s.strip() for s in sections if s.strip()]


def _extract_keywords(text: str) -> set[str]:
    """
    Pull meaningful words from ticket title + description.
    These become the search terms for scoring codebase sections.
    """
    stop_words = {
        "the", "a", "an", "is", "in", "on", "at", "to", "for", "of",
        "and", "or", "but", "with", "this", "that", "it", "be", "as",
        "are", "was", "not", "we", "by", "from", "when", "user", "should",
    }
    words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b', text.lower())
    return {w for w in words if w not in stop_words}


def _score_section(section: str, keywords: set[str]) -> int:
    """
    Score a codebase section by how many ticket keywords appear in it.
    Higher score = more relevant to this ticket.
    """
    section_lower = section.lower()
    return sum(1 for kw in keywords if kw in section_lower)


def _detect_conflicts(
    open_prs: list[PullRequest], keywords: set[str]
) -> list[PullRequest]:
    """
    Find open PRs that likely touch files related to this ticket.
    If PR #14 already modifies auth.py and our ticket is about authentication,
    we flag it so the agent knows before planning.
    """
    conflicting = []
    for pr in open_prs:
        for file_path in pr.changed_files:
            if any(kw in file_path.lower() for kw in keywords):
                conflicting.append(pr)
                break
    return conflicting


def _check_ambiguity(ticket: JiraTicket) -> tuple[bool, str | None]:
    """
    Check if the ticket is too vague for the agent to proceed safely.
    The agent must never guess intent — it asks first.
    """
    if not ticket.description or len(ticket.description.strip()) < 30:
        return True, (
            "Ticket description is too short or missing. "
            "Please add more detail before assigning to the agent."
        )

    vague_phrases = ["fix it", "make it work", "something is wrong", "look into", "check this"]
    for phrase in vague_phrases:
        if phrase in ticket.description.lower():
            return True, (
                f"Ticket contains vague language: '{phrase}'. "
                "Please describe specifically what needs to change and why."
            )

    return False, None


def _count_tokens(text: str) -> int:
    """
    Exact token count using tiktoken.
    Called before every LLM request to ensure we stay within limits.
    """
    return len(ENCODING.encode(text))


# Single shared instance
context_engineer = ContextEngineer()
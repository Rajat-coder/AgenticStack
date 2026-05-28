import logging
from dataclasses import dataclass

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)


@dataclass
class JiraTicket:
    """Clean representation of a JIRA ticket — what the agent actually needs."""
    ticket_id: str
    title: str
    description: str
    status: str
    acceptance_criteria: str
    assigned_to: str = ""


class JiraClient:

    def __init__(self):
        self.base_url = settings.jira_base_url.rstrip("/")
        self.auth = (settings.jira_email, settings.jira_api_token)
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def get_ticket(self, ticket_id: str) -> JiraTicket:
        """
        Fetch a JIRA ticket and return clean, structured data.
        The agent calls this — it never touches raw JIRA API responses.
        """
        url = f"{self.base_url}/rest/api/3/issue/{ticket_id}"

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, auth=self.auth, headers=self.headers)
            response.raise_for_status()
            data = response.json()

        fields = data["fields"]

        return JiraTicket(
            ticket_id=ticket_id,
            title=fields.get("summary", ""),
            description=_adf_to_text(fields.get("description")),
            status=fields.get("status", {}).get("name", ""),
            acceptance_criteria=_extract_acceptance_criteria(fields),
        )

    async def update_status(self, ticket_id: str, target_status: str) -> None:
        """
        Move a JIRA ticket to a new status using the transitions API.
        Example: update_status("AT-42", "In Review")
        """
        transitions_url = f"{self.base_url}/rest/api/3/issue/{ticket_id}/transitions"

        async with httpx.AsyncClient(timeout=30) as client:

            # Step 1 — ask JIRA what transitions are available for this ticket
            response = await client.get(
                transitions_url, auth=self.auth, headers=self.headers
            )
            response.raise_for_status()
            available = response.json()["transitions"]

            # Step 2 — find the transition that leads to our target status
            transition_id = None
            for t in available:
                if t["to"]["name"].lower() == target_status.lower():
                    transition_id = t["id"]
                    break

            if not transition_id:
                logger.warning(
                    "No transition to '%s' found for ticket %s. Available: %s",
                    target_status,
                    ticket_id,
                    [t["to"]["name"] for t in available],
                )
                return

            # Step 3 — execute the transition
            await client.post(
                transitions_url,
                auth=self.auth,
                headers=self.headers,
                json={"transition": {"id": transition_id}},
            )
            logger.info("Ticket %s → %s", ticket_id, target_status)
        
    async def get_project_tickets(self, max_results: int = 50) -> list["JiraTicket"]:
        """
        Fetch all tickets in the configured JIRA project.
        Uses GET /rest/api/3/search/jql — JIRA's current search endpoint (2024+).
        """
        url = f"{self.base_url}/rest/api/3/search/jql"
        params = {
            "jql": f"project = {settings.jira_project_key} ORDER BY created DESC",
            "maxResults": max_results,
            "fields": "summary,description,status,assignee",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                url, params=params, auth=self.auth, headers=self.headers
            )
            response.raise_for_status()
            data = response.json()

        tickets = []
        for issue in data.get("issues", []):
            fields = issue.get("fields", {})
            desc_raw = fields.get("description")
            description = (
                _adf_to_text(desc_raw) if isinstance(desc_raw, dict) else (desc_raw or "")
            )
            tickets.append(JiraTicket(
                ticket_id=issue["key"],
                title=fields.get("summary", ""),
                description=description,
                status=fields.get("status", {}).get("name", ""),
                acceptance_criteria=_extract_acceptance_criteria(fields),
                assigned_to=fields.get("assignee", {}).get("displayName", "Unassigned") if fields.get("assignee") else "Unassigned",
            ))
        return tickets

    async def get_my_tickets(self, max_results: int = 50) -> list["JiraTicket"]:
        """
        Fetch tickets assigned to the authenticated JIRA user.
        Uses currentUser() in JQL — always refers to whoever's API token is in .env.
        """
        url = f"{self.base_url}/rest/api/3/search/jql"
        params = {
            "jql": f"project = {settings.jira_project_key} AND assignee = currentUser() ORDER BY created DESC",
            "maxResults": max_results,
            "fields": "summary,description,status,assignee",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                url, params=params, auth=self.auth, headers=self.headers
            )
            response.raise_for_status()
            data = response.json()

        tickets = []
        for issue in data.get("issues", []):
            fields = issue.get("fields", {})
            desc_raw = fields.get("description")
            description = (
                _adf_to_text(desc_raw) if isinstance(desc_raw, dict) else (desc_raw or "")
            )
            tickets.append(JiraTicket(
                ticket_id=issue["key"],
                title=fields.get("summary", ""),
                description=description,
                status=fields.get("status", {}).get("name", ""),
                acceptance_criteria=_extract_acceptance_criteria(fields),
                assigned_to=fields.get("assignee", {}).get("displayName", "Unassigned") if fields.get("assignee") else "Unassigned",
            ))
        return tickets


# ------------------------------------------------------------------
# ADF (Atlassian Document Format) → plain text
# JIRA stores rich text as a nested JSON tree.
# We recursively walk the tree and extract text nodes.
# ------------------------------------------------------------------

def _adf_to_text(adf: dict | None) -> str:
    if not adf:
        return ""
    parts: list[str] = []
    _walk(adf, parts)
    return "\n".join(p for p in parts if p).strip()


def _walk(node: dict, parts: list[str]) -> None:
    # If this node is a text node, grab its content
    if node.get("type") == "text":
        parts.append(node.get("text", ""))
        return

    # Recurse into children
    for child in node.get("content", []):
        _walk(child, parts)

    # Add a blank line after block elements to preserve structure
    if node.get("type") in ("paragraph", "heading", "bulletList", "listItem", "blockquote"):
        parts.append("")


def _extract_acceptance_criteria(fields: dict) -> str:
    """
    Acceptance criteria can live in a custom JIRA field.
    We scan all fields for anything with 'acceptance' in the key name.
    """
    for key, value in fields.items():
        if "acceptance" in key.lower() and value:
            if isinstance(value, dict):
                return _adf_to_text(value)
            if isinstance(value, str):
                return value
    return ""


# Single shared instance — import this everywhere
jira = JiraClient()
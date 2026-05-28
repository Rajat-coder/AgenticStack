from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.integrations.jira import jira

router = APIRouter(prefix="/tickets", tags=["tickets"])


class TicketResponse(BaseModel):
    ticket_id: str
    title: str
    description: str
    status: str
    acceptance_criteria: str
    assigned_to: str = "" 


@router.get("", response_model=list[TicketResponse])
async def list_tickets():
    """
    Fetch all tickets from the JIRA project.
    The dashboard calls this to populate the ticket board.
    """
    tickets = await jira.get_project_tickets()
    return [
        TicketResponse(
            ticket_id=t.ticket_id,
            title=t.title,
            description=t.description,
            status=t.status,
            acceptance_criteria=t.acceptance_criteria,
            assigned_to=t.assigned_to,
        )
        for t in tickets
    ]

@router.get("/mine", response_model=list[TicketResponse])
async def my_tickets():
    """
    Fetch tickets assigned to the authenticated JIRA user.
    Uses currentUser() — whoever's API token is configured in .env.
    """
    tickets = await jira.get_my_tickets()
    return [
        TicketResponse(
            ticket_id=t.ticket_id,
            title=t.title,
            description=t.description,
            status=t.status,
            acceptance_criteria=t.acceptance_criteria,
            assigned_to=t.assigned_to,
        )
        for t in tickets
    ]

@router.get("/{ticket_id}", response_model=TicketResponse)
async def get_ticket(ticket_id: str):
    """Fetch one JIRA ticket by ID."""
    try:
        ticket = await jira.get_ticket(ticket_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Ticket not found: {exc}")

    return TicketResponse(
        ticket_id=ticket.ticket_id,
        title=ticket.title,
        description=ticket.description,
        status=ticket.status,
        acceptance_criteria=ticket.acceptance_criteria,
    )
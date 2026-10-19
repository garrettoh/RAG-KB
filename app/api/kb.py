"""Knowledge draft generation; publication requires a separate review action."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from sqlalchemy.orm import Session

from app.agent_processor import DraftProvider, create_draft_provider, process_ticket
from app.api.dependencies import get_app_settings, require_management_auth
from app.database import get_db
from app.models import RawTicket


router = APIRouter(prefix="/api/v1/kb", tags=["Knowledge base"], dependencies=[Depends(require_management_auth)])


async def get_draft_provider(request: Request):
    factory = getattr(request.app.state, "draft_provider_factory", create_draft_provider)
    provider = factory(get_app_settings(request))
    try:
        yield provider
    finally:
        await provider.aclose()


@router.post("/drafts/from-ticket/{ticket_id}")
async def draft_from_ticket(ticket_id: Annotated[int, Path(gt=0)], session: Session = Depends(get_db),
                            provider: DraftProvider = Depends(get_draft_provider)):
    ticket = session.get(RawTicket, ticket_id)
    if ticket is None:
        raise HTTPException(404, "Source ticket not found.")
    draft = await process_ticket(session, ticket, provider)
    session.commit()
    return {key: getattr(draft, key) for key in ("article_id", "scope", "target_tenant_id", "category", "title",
                                                "summary", "markdown_steps", "status")}

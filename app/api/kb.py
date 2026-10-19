"""Knowledge draft generation; publication requires a separate review action."""

from typing import Annotated
import re

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BeforeValidator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent_processor import DraftProvider, create_draft_provider, process_ticket
from app.api.dependencies import get_app_settings, require_management_auth
from app.database import get_db
from app.models import KBDraft, RawTicket
from app.vector_db import get_app_store, index_article, search_knowledge_base


router = APIRouter(prefix="/api/v1/kb", tags=["Knowledge base"], dependencies=[Depends(require_management_auth)])


def parse_tenant_query(value):
    if value is None:
        return value
    if not isinstance(value, str) or re.fullmatch(r"[1-9][0-9]*", value) is None:
        raise ValueError("tenant_id must be a positive integer.")
    return int(value)


def draft_response(draft: KBDraft) -> dict:
    return {key: getattr(draft, key) for key in ("article_id", "scope", "target_tenant_id", "category", "title",
                                                "summary", "markdown_steps", "status")}


@router.get("/drafts")
def list_drafts(session: Session = Depends(get_db),
                limit: Annotated[int, Query(ge=1, le=500)] = 100,
                offset: Annotated[int, Query(ge=0)] = 0):
    return [draft_response(row) for row in session.scalars(select(KBDraft).order_by(KBDraft.article_id).limit(limit).offset(offset))]


@router.get("/drafts/{article_id}")
def get_draft(article_id: Annotated[int, Path(gt=0)], session: Session = Depends(get_db)):
    row = session.get(KBDraft, article_id)
    if row is None:
        raise HTTPException(404, "Knowledge draft not found.")
    return draft_response(row)


@router.post("/drafts/{article_id}/approve")
def approve_draft(article_id: Annotated[int, Path(gt=0)], request: Request, session: Session = Depends(get_db)):
    row = session.get(KBDraft, article_id)
    if row is None:
        raise HTTPException(404, "Knowledge draft not found.")
    row.status = "approved"
    session.commit()  # Durable review gate, even if lazy provider initialization fails.
    index_article(session, row, get_app_store(request.app))
    return draft_response(row)


@router.get("/search")
def search(request: Request, query_str: Annotated[str, Query(min_length=1, max_length=4000)],
           tenant_id: Annotated[int | None, BeforeValidator(parse_tenant_query), Query(gt=0)] = None,
           limit: Annotated[int, Query(ge=1, le=100)] = 10, session: Session = Depends(get_db)):
    if not query_str.strip():
        raise HTTPException(422, "query_str must not be blank.")
    return search_knowledge_base(query_str, tenant_id, store=get_app_store(request.app), session=session, limit=limit)


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
    return draft_response(draft)

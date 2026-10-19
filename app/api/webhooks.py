"""Closure notification intake and manual company synchronization."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.dependencies import get_connectwise_client, require_management_auth, require_webhook_auth
from app.connectwise_client import ConnectWiseSource
from app.database import get_db
from app.ingestion import ingest_ticket, sync_company


router = APIRouter(prefix="/api/v1", tags=["ConnectWise"])


class TicketClosureEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket_id: int = Field(gt=0, strict=True)


@router.post("/webhooks/connectwise", dependencies=[Depends(require_webhook_auth)])
async def connectwise_webhook(event: TicketClosureEvent, session: Session = Depends(get_db),
                             client: ConnectWiseSource = Depends(get_connectwise_client)):
    row = await ingest_ticket(session, client, event.ticket_id)
    session.commit()
    return {"status": "ingested" if row is not None else "ignored", "ticket_id": event.ticket_id}


@router.post("/connectwise/sync/{company_id}", dependencies=[Depends(require_management_auth)])
async def connectwise_sync(company_id: Annotated[int, Path(gt=0)], session: Session = Depends(get_db),
                          client: ConnectWiseSource = Depends(get_connectwise_client)):
    counts = await sync_company(session, client, company_id)
    session.commit()
    return counts

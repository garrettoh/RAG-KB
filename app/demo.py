"""Run ``python -m app.demo`` to seed synthetic pending drafts, never approve."""

import asyncio
from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent_processor import LocalDraftProvider, process_ticket
from app.config import Settings, get_settings
from app.database import Base, create_db_engine
from app.demo_data import DemoConnectWiseClient
from app.ingestion import ingest_ticket, sync_company
from app.models import KBDraft


class _SeedClient(DemoConnectWiseClient):
    """Additional tenant example, preserving the existing two-record fixtures."""

    ticket = {"id": 2002, "company": {"id": 202, "name": "Example Harbor"}, "closedFlag": True,
              "summary": "Harbor office network connection restored",
              "internalAnalysis": "The synthetic harbor-switch serves this office's local network.",
              "resolution": "Reconnected the office network uplink cable and verified connectivity."}

    async def fetch_ticket(self, ticket_id: int) -> dict:
        if ticket_id == 2002:
            return deepcopy(self.ticket)
        return await super().fetch_ticket(ticket_id)


async def _seed(session: Session) -> None:
    async with _SeedClient() as client:
        for company in (101, 202):
            await sync_company(session, client, company)
        await ingest_ticket(session, client, 2002)
        # Reserved synthetic draft titles identify seed records without a schema
        # migration or altering reviewed content on subsequent CLI invocations.
        provider = LocalDraftProvider()
        try:
            for ticket_id in (1001, 2001, 2002):
                ticket = await ingest_ticket(session, client, ticket_id)
                title = f"Synthetic demo ticket {ticket_id}"
                if session.scalar(select(KBDraft).where(KBDraft.title == title)) is None:
                    row = await process_ticket(session, ticket, provider)
                    row.title = title
                    session.flush()
        finally:
            await provider.aclose()


def seed_demo(settings: Settings | None = None) -> None:
    """Only synthetic + local drafting, regardless of configured live providers."""
    selected = settings if settings is not None else get_settings()
    engine = create_db_engine(selected.database_url)
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            asyncio.run(_seed(session))
            session.commit()
    finally:
        engine.dispose()


def main() -> None:
    seed_demo()
    print("Synthetic tickets/assets and pending drafts seeded. Review /api/v1/kb/drafts, then explicitly approve each article.")


if __name__ == "__main__":
    main()

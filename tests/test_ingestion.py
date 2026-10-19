import asyncio

import pytest
from sqlalchemy import func, select


class Source:
    def __init__(self):
        self.ticket = {"id": 7, "company": {"id": 101}, "closedFlag": True,
                       "summary": "Network repaired", "internalAnalysis": "Checked switch",
                       "resolution": "Restarted switch"}
        self.entries = [
            {"id": 1, "notes": "Investigated", "internalNotes": "Checked logs", "addToInternalAnalysisFlag": True},
            {"id": 2, "notes": "Verified connectivity", "addToResolutionFlag": True},
            {"id": 3, "notes": "Customer message"},
        ]
        self.assets = [{"id": 80, "company": {"id": 101}, "name": "Demo switch",
                        "serialNumber": "SYNTHETIC", "type": {"name": "Switch"}, "osType": "DemoOS"}]

    async def fetch_ticket(self, ticket_id):
        return self.ticket

    async def fetch_time_entries(self, ticket_id):
        return self.entries

    async def fetch_closed_tickets(self, company_id=None):
        return [self.ticket]

    async def fetch_configurations(self, company_id):
        return self.assets


def test_ingest_aggregates_notes_preserves_raw_and_updates_idempotently(session):
    from app.ingestion import ingest_ticket
    from app.models import RawTicket

    source = Source()
    ticket = asyncio.run(ingest_ticket(session, source, 7))
    session.commit()
    assert ticket.company_id == 101
    assert ticket.internal_notes == "Checked switch\n\nChecked logs\n\nInvestigated"
    assert ticket.resolution == "Restarted switch\n\nVerified connectivity"
    assert ticket.raw_payload == {"ticket": source.ticket, "time_entries": source.entries}
    source.ticket["summary"] = "Updated title"
    asyncio.run(ingest_ticket(session, source, 7))
    session.commit()
    assert session.scalar(select(func.count()).select_from(RawTicket)) == 1
    assert session.get(RawTicket, 7).summary == "Updated title"


@pytest.mark.parametrize("closed", [False, None, "true", 1])
def test_only_authoritatively_closed_tickets_are_ingested(session, closed):
    from app.ingestion import ingest_ticket
    from app.models import RawTicket

    source = Source()
    source.ticket["closedFlag"] = closed
    assert asyncio.run(ingest_ticket(session, source, 7)) is None
    assert session.get(RawTicket, 7) is None


def test_existing_ticket_cannot_move_to_another_company(session):
    from app.ingestion import IngestionConflict, ingest_ticket
    from app.models import RawTicket

    source = Source()
    asyncio.run(ingest_ticket(session, source, 7))
    session.commit()
    source.ticket["company"]["id"] = 202
    with pytest.raises(IngestionConflict):
        asyncio.run(ingest_ticket(session, source, 7))
    session.rollback()
    assert session.get(RawTicket, 7).company_id == 101


def test_sync_updates_tenant_assets_without_duplicates(session):
    from app.ingestion import sync_company
    from app.models import TenantAsset

    source = Source()
    assert asyncio.run(sync_company(session, source, 101)) == {"tickets": 1, "assets": 1}
    session.commit()
    source.assets[0]["name"] = "Renamed switch"
    asyncio.run(sync_company(session, source, 101))
    session.commit()
    assert session.scalar(select(func.count()).select_from(TenantAsset)) == 1
    asset = session.get(TenantAsset, 80)
    assert (asset.asset_name, asset.serial_number, asset.type, asset.os) == ("Renamed switch", "SYNTHETIC", "Switch", "DemoOS")


@pytest.mark.parametrize("resource", ["ticket", "asset", "existing_asset"])
def test_sync_rejects_company_mismatches_and_can_roll_back_batch(session, resource):
    from app.ingestion import IngestionConflict, sync_company
    from app.models import RawTicket, TenantAsset

    source = Source()
    if resource == "ticket":
        source.ticket["company"]["id"] = 202
    elif resource == "asset":
        source.assets[0]["company"]["id"] = 202
    else:
        session.add(TenantAsset(asset_id=80, company_id=202, asset_name="Other tenant", serial_number="", type="", os=""))
        session.commit()
    with pytest.raises(IngestionConflict):
        asyncio.run(sync_company(session, source, 101))
    session.rollback()
    assert session.get(RawTicket, 7) is None
    if resource == "existing_asset":
        assert session.get(TenantAsset, 80).company_id == 202


@pytest.mark.parametrize("mutation", ["id", "company", "summary", "entries"])
def test_malformed_remote_ticket_is_an_integration_error(session, mutation):
    from app.connectwise_client import IntegrationError
    from app.ingestion import ingest_ticket

    source = Source()
    if mutation == "id":
        source.ticket["id"] = 99
    elif mutation == "company":
        source.ticket["company"] = None
    elif mutation == "summary":
        source.ticket["summary"] = {"wrong": "type"}
    else:
        source.entries = ["wrong"]
    with pytest.raises(IntegrationError):
        asyncio.run(ingest_ticket(session, source, 7))

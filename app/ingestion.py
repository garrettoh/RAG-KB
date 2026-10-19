"""Idempotent source persistence. Callers commit or roll back the whole operation."""

from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from app.connectwise_client import ConnectWiseSource, IntegrationError, positive_id
from app.models import RawTicket, TenantAsset


class IngestionConflict(Exception):
    """An external identifier would overwrite another company's data."""


def _text(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise IntegrationError("ConnectWise returned a non-text content field.")
    return value.strip()


def _company(record: dict) -> int:
    company = record.get("company")
    if not isinstance(company, dict):
        raise IntegrationError("ConnectWise returned a resource without a company.")
    return positive_id(company.get("id"))


async def ingest_ticket(session: Session, client: ConnectWiseSource, ticket_id: int,
                        *, expected_company_id: int | None = None) -> RawTicket | None:
    """Fetch authoritative state and store closed tickets only; does not commit."""
    positive_id(ticket_id)
    ticket = await client.fetch_ticket(ticket_id)
    if not isinstance(ticket, dict) or positive_id(ticket.get("id")) != ticket_id:
        raise IntegrationError("ConnectWise returned a different ticket identifier.")
    if ticket.get("closedFlag") is not True:
        return None
    company_id = _company(ticket)
    if expected_company_id is not None and company_id != expected_company_id:
        raise IngestionConflict("ConnectWise ticket company does not match the requested company.")
    entries = await client.fetch_time_entries(ticket_id)
    if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
        raise IntegrationError("ConnectWise returned invalid time entries.")
    internal = [_text(ticket.get("internalAnalysis"))]
    resolution = [_text(ticket.get("resolution"))]
    for entry in entries:
        internal.append(_text(entry.get("internalNotes")))
        notes = _text(entry.get("notes"))
        if entry.get("addToInternalAnalysisFlag") is True:
            internal.append(notes)
        if entry.get("addToResolutionFlag") is True:
            resolution.append(notes)
    values = dict(company_id=company_id, summary=_text(ticket.get("summary")),
                  internal_notes="\n\n".join(part for part in internal if part),
                  resolution="\n\n".join(part for part in resolution if part),
                  raw_payload=deepcopy({"ticket": ticket, "time_entries": entries}))
    row = session.get(RawTicket, ticket_id)
    if row is None:
        row = RawTicket(ticket_id=ticket_id, **values)
        session.add(row)
    else:
        if row.company_id != company_id:
            raise IngestionConflict("ConnectWise ticket identifier belongs to another company.")
        for name, value in values.items():
            setattr(row, name, value)
    session.flush()
    return row


async def sync_company(session: Session, client: ConnectWiseSource, company_id: int) -> dict[str, int]:
    """Sync authoritative closed tickets/configurations; caller owns the transaction."""
    positive_id(company_id)
    tickets = await client.fetch_closed_tickets(company_id)
    ticket_count = 0
    for ticket in tickets:
        if not isinstance(ticket, dict):
            raise IntegrationError("ConnectWise returned an invalid ticket list.")
        if _company(ticket) != company_id:
            raise IngestionConflict("ConnectWise ticket list contains another company.")
        row = await ingest_ticket(session, client, positive_id(ticket.get("id")), expected_company_id=company_id)
        ticket_count += row is not None
    configurations = await client.fetch_configurations(company_id)
    for asset in configurations:
        if not isinstance(asset, dict):
            raise IntegrationError("ConnectWise returned an invalid configuration.")
        if _company(asset) != company_id:
            raise IngestionConflict("ConnectWise configuration company does not match the requested company.")
        asset_id = positive_id(asset.get("id"))
        asset_type = asset.get("type") or {}
        if not isinstance(asset_type, dict):
            raise IntegrationError("ConnectWise returned an invalid configuration type.")
        values = dict(company_id=company_id, asset_name=_text(asset.get("name")),
                      serial_number=_text(asset.get("serialNumber")), type=_text(asset_type.get("name")),
                      os=_text(asset.get("osType")))
        row = session.get(TenantAsset, asset_id)
        if row is None:
            session.add(TenantAsset(asset_id=asset_id, **values))
        else:
            if row.company_id != company_id:
                raise IngestionConflict("ConnectWise configuration identifier belongs to another company.")
            for name, value in values.items():
                setattr(row, name, value)
        session.flush()
    return {"tickets": ticket_count, "assets": len(configurations)}

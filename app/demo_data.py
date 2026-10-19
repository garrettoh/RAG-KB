"""Synthetic records only. No customer data, credentials or remote calls."""

from copy import deepcopy

from app.connectwise_client import IntegrationError, positive_id


DEMO_COMPANY_IDS = (101, 202)
DEMO_TICKETS = (
    {"id": 1001, "company": {"id": 101, "name": "Example Orchard"}, "closedFlag": True,
     "summary": "Orchard office network connection restored",
     "internalAnalysis": "The synthetic orchard-switch serves this office's local network.",
     "resolution": "Reconnected the loose uplink cable and verified office connectivity."},
    {"id": 2001, "company": {"id": 202, "name": "Example Harbor"}, "closedFlag": True,
     "summary": "PDF application display settings restored",
     "internalAnalysis": "The PDF toolbar was hidden after a display preference change.",
     "resolution": "Opened View > Toolbars and enabled the standard toolbar. Reopened a sample PDF to verify."},
)
DEMO_TIME_ENTRIES = {
    1001: [{"id": 1101, "notes": "Verified the office uplink remained stable.", "addToResolutionFlag": True}],
    2001: [{"id": 2101, "notes": "Confirmed toolbar preference persisted after restart.", "addToResolutionFlag": True}],
}
DEMO_CONFIGURATIONS = (
    {"id": 110, "company": {"id": 101}, "name": "orchard-switch", "serialNumber": "SYNTHETIC-ORCHARD-01",
     "type": {"name": "Switch"}, "osType": "Demo network OS"},
    {"id": 220, "company": {"id": 202}, "name": "harbor-workstation", "serialNumber": "SYNTHETIC-HARBOR-01",
     "type": {"name": "Workstation"}, "osType": "Demo desktop OS"},
)


class DemoConnectWiseClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()

    async def aclose(self) -> None:
        pass

    async def fetch_closed_tickets(self, company_id: int | None = None) -> list[dict]:
        if company_id is not None:
            positive_id(company_id)
        return deepcopy([item for item in DEMO_TICKETS if company_id is None or item["company"]["id"] == company_id])

    async def fetch_ticket(self, ticket_id: int) -> dict:
        positive_id(ticket_id)
        for ticket in DEMO_TICKETS:
            if ticket["id"] == ticket_id:
                return deepcopy(ticket)
        raise IntegrationError("ConnectWise demo ticket not found; use ticket 1001 or 2001.")

    async def fetch_time_entries(self, ticket_id: int) -> list[dict]:
        positive_id(ticket_id)
        return deepcopy(DEMO_TIME_ENTRIES.get(ticket_id, []))

    async def fetch_configurations(self, company_id: int) -> list[dict]:
        positive_id(company_id)
        return deepcopy([item for item in DEMO_CONFIGURATIONS if item["company"]["id"] == company_id])

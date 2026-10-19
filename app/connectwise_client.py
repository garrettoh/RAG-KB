"""Read-only ConnectWise Manage adapter; never falls back to demo on failure."""

from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from app.config import Settings


class IntegrationError(Exception):
    """A safe, actionable upstream error without response bodies or credentials."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class ConnectWiseSource(Protocol):
    async def fetch_closed_tickets(self, company_id: int | None = None) -> list[dict[str, Any]]: ...
    async def fetch_ticket(self, ticket_id: int) -> dict[str, Any]: ...
    async def fetch_time_entries(self, ticket_id: int) -> list[dict[str, Any]]: ...
    async def fetch_configurations(self, company_id: int) -> list[dict[str, Any]]: ...
    async def aclose(self) -> None: ...


def positive_id(value: Any) -> int:
    if type(value) is not int or value <= 0:
        raise IntegrationError("ConnectWise returned an invalid resource identifier.")
    return value


class ConnectWiseClient:
    """Use a full API root URL ending in /apis/3.0, with bounded pagination."""

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None,
                 page_size: int = 100, max_pages: int = 1000):
        names = ("connectwise_url", "connectwise_company_id", "connectwise_public_key",
                 "connectwise_private_key", "connectwise_client_id")
        missing = [name.upper() for name in names if not getattr(settings, name)]
        if missing:
            raise IntegrationError("Configure live ConnectWise settings: " + ", ".join(missing), 503)
        root = settings.connectwise_url
        parsed = urlsplit(root)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise IntegrationError("CONNECTWISE_URL must be an HTTPS API root without credentials, query, or fragment.", 503)
        if not 1 <= page_size <= 1000 or max_pages < 1:
            raise ValueError("page_size must be 1..1000 and max_pages must be positive")
        self.page_size = page_size
        self.max_pages = max_pages
        self.http_client = httpx.AsyncClient(
            base_url=root.rstrip("/") + "/",
            auth=httpx.BasicAuth(f"{settings.connectwise_company_id}+{settings.connectwise_public_key.get_secret_value()}",
                                settings.connectwise_private_key.get_secret_value()),
            headers={"clientId": settings.connectwise_client_id.get_secret_value(), "Accept": "application/json"},
            timeout=httpx.Timeout(settings.connectwise_timeout_seconds),
            follow_redirects=False,
            transport=transport,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()

    async def aclose(self) -> None:
        await self.http_client.aclose()

    async def _get(self, path: str, params: dict | None = None) -> Any:
        try:
            response = await self.http_client.get(path, params=params)
        except httpx.RequestError:
            raise IntegrationError("ConnectWise request failed; check connectivity and timeout settings.", 503) from None
        if not response.is_success:
            if response.status_code in (401, 403):
                detail = "check API credentials, client ID and member permissions"
            elif response.status_code == 429:
                detail = "rate limit reached; retry later"
            elif response.status_code == 404:
                detail = "resource not found; check the API root and identifier"
            else:
                detail = "upstream service unavailable; retry later"
            raise IntegrationError(f"ConnectWise HTTP {response.status_code}: {detail}.")
        try:
            return response.json()
        except ValueError:
            raise IntegrationError("ConnectWise returned invalid JSON; check the API root.") from None

    async def _list(self, path: str, conditions: str) -> list[dict[str, Any]]:
        result = []
        for page in range(1, self.max_pages + 1):
            data = await self._get(path, {"conditions": conditions, "page": page,
                                          "pageSize": self.page_size, "orderBy": "id asc"})
            if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
                raise IntegrationError("ConnectWise returned an invalid resource list.")
            result.extend(data)
            if len(data) < self.page_size:
                return result
        raise IntegrationError("ConnectWise pagination limit reached; sync a smaller selection.")

    async def fetch_closed_tickets(self, company_id: int | None = None) -> list[dict[str, Any]]:
        conditions = "closedFlag=true"
        if company_id is not None:
            conditions += f" AND company/id={positive_id(company_id)}"
        return await self._list("service/tickets", conditions)

    async def fetch_ticket(self, ticket_id: int) -> dict[str, Any]:
        data = await self._get(f"service/tickets/{positive_id(ticket_id)}")
        if not isinstance(data, dict):
            raise IntegrationError("ConnectWise returned an invalid ticket.")
        return data

    async def fetch_time_entries(self, ticket_id: int) -> list[dict[str, Any]]:
        return await self._list("time/entries", f'chargeToType="ServiceTicket" AND chargeToId={positive_id(ticket_id)}')

    async def fetch_configurations(self, company_id: int) -> list[dict[str, Any]]:
        return await self._list("company/configurations", f"company/id={positive_id(company_id)}")

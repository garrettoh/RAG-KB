import asyncio
import base64

import httpx
import pytest


def live_settings(**overrides):
    from app.config import Settings

    values = dict(demo_mode=False, connectwise_url="https://cw.example.test/v4_6_release/apis/3.0",
                  connectwise_company_id="login", connectwise_public_key="public",
                  connectwise_private_key="private", connectwise_client_id="client", _env_file=None)
    values.update(overrides)
    return Settings(**values)


def test_http_client_auth_pagination_and_resource_filters():
    from app.connectwise_client import ConnectWiseClient

    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["authorization"] == "Basic " + base64.b64encode(b"login+public:private").decode()
        assert request.headers["clientId"] == "client"
        assert request.extensions["timeout"]["read"] == 15
        path = request.url.path
        params = request.url.params
        if path.endswith("/service/tickets/7"):
            return httpx.Response(200, json={"id": 7, "closedFlag": True})
        assert params["pageSize"] == "2"
        assert params["orderBy"] == "id asc"
        if path.endswith("/service/tickets"):
            assert params["conditions"] == "closedFlag=true AND company/id=101"
            data = [{"id": 7}, {"id": 8}] if params["page"] == "1" else [{"id": 9}]
        elif path.endswith("/time/entries"):
            assert params["conditions"] == 'chargeToType="ServiceTicket" AND chargeToId=7'
            data = [{"id": 70}]
        else:
            assert path.endswith("/company/configurations")
            assert params["conditions"] == "company/id=101"
            data = [{"id": 80}]
        return httpx.Response(200, json=data)

    async def exercise():
        async with ConnectWiseClient(live_settings(), transport=httpx.MockTransport(handler), page_size=2) as client:
            assert await client.fetch_closed_tickets(101) == [{"id": 7}, {"id": 8}, {"id": 9}]
            assert (await client.fetch_ticket(7))["closedFlag"] is True
            assert await client.fetch_time_entries(7) == [{"id": 70}]
            assert await client.fetch_configurations(101) == [{"id": 80}]
        assert client.http_client.is_closed

    asyncio.run(exercise())
    assert len(requests) == 5


@pytest.mark.parametrize("kind", ["unauthorized", "rate_limit", "server", "timeout", "json", "shape"])
def test_remote_failures_are_actionable_and_do_not_expose_secrets(kind):
    from app.connectwise_client import ConnectWiseClient, IntegrationError

    def handler(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("private secret URL", request=request)
        if kind == "json":
            return httpx.Response(200, text="private")
        if kind == "shape":
            return httpx.Response(200, json={"unexpected": "private"})
        return httpx.Response({"unauthorized": 401, "rate_limit": 429, "server": 500}[kind], text="private")

    async def exercise():
        async with ConnectWiseClient(live_settings(), transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(IntegrationError) as caught:
                await client.fetch_closed_tickets()
        assert "private" not in str(caught.value)
        assert "ConnectWise" in str(caught.value)

    asyncio.run(exercise())


def test_missing_live_credentials_fail_on_use():
    from app.connectwise_client import ConnectWiseClient, IntegrationError
    from app.config import Settings

    with pytest.raises(IntegrationError, match="CONNECTWISE"):
        ConnectWiseClient(Settings(demo_mode=False, _env_file=None))


def test_demo_data_has_two_companies_and_returns_detached_copies():
    from app.demo_data import DemoConnectWiseClient

    async def exercise():
        async with DemoConnectWiseClient() as client:
            tickets = await client.fetch_closed_tickets()
            assert {ticket["company"]["id"] for ticket in tickets} == {101, 202}
            ticket = tickets[0]
            ticket["summary"] = "modified"
            assert (await client.fetch_ticket(ticket["id"]))["summary"] != "modified"
            assert await client.fetch_time_entries(ticket["id"])
            assert await client.fetch_configurations(101)
    asyncio.run(exercise())

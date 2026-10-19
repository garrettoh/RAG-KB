import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select


def test_demo_webhook_replays_and_company_sync(application):
    from app.models import RawTicket, TenantAsset

    with TestClient(application) as client:
        for _ in range(2):
            response = client.post("/api/v1/webhooks/connectwise", json={"ticket_id": 1001})
            assert response.status_code == 200
            assert response.json() == {"status": "ingested", "ticket_id": 1001}
        assert client.post("/api/v1/connectwise/sync/202").json() == {"tickets": 1, "assets": 1}
        with application.state.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(RawTicket)) == 2
            assert session.scalar(select(func.count()).select_from(TenantAsset)) == 1


@pytest.mark.parametrize("payload", [{}, {"ticket_id": -1}, {"ticket_id": "abc"}, {"ticket_id": True}, {"ticket_id": 1, "company_id": 202}])
def test_invalid_webhook_payload_is_422(application, payload):
    with TestClient(application) as client:
        assert client.post("/api/v1/webhooks/connectwise", json=payload).status_code == 422


@pytest.mark.parametrize("route,headers", [
    ("/api/v1/webhooks/connectwise", {}),
    ("/api/v1/webhooks/connectwise", {"X-Webhook-Secret": "wrong"}),
    ("/api/v1/connectwise/sync/101", {}),
    ("/api/v1/connectwise/sync/101", {"Authorization": "Bearer webhook-secret"}),
])
def test_live_routes_require_separate_secrets(tmp_path, route, headers):
    from app.config import Settings
    from app.main import create_app

    app = create_app(Settings(database_url="sqlite:///:memory:", demo_mode=False,
                              webhook_secret="webhook-secret", management_token="management-secret", _env_file=None))
    with TestClient(app) as client:
        assert client.post(route, json={"ticket_id": 1001}, headers=headers).status_code == 401


@pytest.mark.parametrize("route,headers", [
    ("/api/v1/webhooks/connectwise", {"X-Webhook-Secret": "anything"}),
    ("/api/v1/connectwise/sync/101", {"Authorization": "Bearer anything"}),
])
def test_live_routes_deny_access_when_secret_is_unconfigured(route, headers):
    from app.config import Settings
    from app.main import create_app

    app = create_app(Settings(database_url="sqlite:///:memory:", demo_mode=False, _env_file=None))
    with TestClient(app) as client:
        assert client.post(route, json={"ticket_id": 1001}, headers=headers).status_code == 503


def test_authorized_live_routes_use_injected_adapter_and_close_it():
    from app.config import Settings
    from app.demo_data import DemoConnectWiseClient
    from app.main import create_app

    closed = []

    class ClosingDemo(DemoConnectWiseClient):
        async def aclose(self):
            closed.append(True)

    app = create_app(Settings(database_url="sqlite:///:memory:", demo_mode=False,
                              webhook_secret="hook", management_token="manage", _env_file=None))
    app.state.connectwise_client_factory = lambda settings: ClosingDemo()
    with TestClient(app) as client:
        assert client.post("/api/v1/webhooks/connectwise", json={"ticket_id": 1001}, headers={"X-Webhook-Secret": "hook"}).status_code == 200
        assert client.post("/api/v1/connectwise/sync/101", headers={"Authorization": "Bearer manage"}).status_code == 200
    assert len(closed) == 2


def test_webhook_ignores_open_ticket_and_hides_remote_error_details(application):
    from app.api.dependencies import get_connectwise_client
    from app.connectwise_client import IntegrationError
    from app.demo_data import DemoConnectWiseClient

    class OpenDemo(DemoConnectWiseClient):
        async def fetch_ticket(self, ticket_id):
            return {"id": ticket_id, "closedFlag": False}

    class BrokenDemo(DemoConnectWiseClient):
        async def fetch_ticket(self, ticket_id):
            raise IntegrationError("ConnectWise request failed; check credentials.")

    with TestClient(application) as client:
        application.dependency_overrides[get_connectwise_client] = lambda: OpenDemo()
        response = client.post("/api/v1/webhooks/connectwise", json={"ticket_id": 1001})
        assert response.json() == {"status": "ignored", "ticket_id": 1001}
        application.dependency_overrides[get_connectwise_client] = lambda: BrokenDemo()
        assert client.post("/api/v1/webhooks/connectwise", json={"ticket_id": 1001}).status_code == 502

"""Per-application providers and live route authentication."""

from collections.abc import AsyncIterator
from secrets import compare_digest

from fastapi import Header, HTTPException, Request

from app.config import Settings
from app.connectwise_client import ConnectWiseClient, ConnectWiseSource
from app.demo_data import DemoConnectWiseClient


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def _check_secret(settings: Settings, name: str, provided: str | None) -> None:
    if settings.demo_mode:
        return
    configured = getattr(settings, name)
    if configured is None or not configured.get_secret_value().strip():
        raise HTTPException(503, "Live route authentication is not configured.")
    if provided is None or not compare_digest(configured.get_secret_value().encode(), provided.encode()):
        raise HTTPException(401, "Invalid or missing credentials.")


async def require_management_auth(request: Request, authorization: str | None = Header(default=None)) -> None:
    scheme, _, token = (authorization or "").partition(" ")
    provided = token if scheme.lower() == "bearer" else None
    _check_secret(get_app_settings(request), "management_token", provided)


async def require_webhook_auth(request: Request, x_webhook_secret: str | None = Header(default=None)) -> None:
    _check_secret(get_app_settings(request), "webhook_secret", x_webhook_secret)


async def get_connectwise_client(request: Request) -> AsyncIterator[ConnectWiseSource]:
    settings = get_app_settings(request)
    factory = getattr(request.app.state, "connectwise_client_factory", None)
    client = factory(settings) if factory else (DemoConnectWiseClient() if settings.demo_mode else ConnectWiseClient(settings))
    try:
        yield client
    finally:
        await client.aclose()

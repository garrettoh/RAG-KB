"""Environment configuration; service credentials are optional during setup."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    database_url: str = "sqlite:///./rag_kb.db"
    demo_mode: bool = True
    management_token: SecretStr | None = None
    webhook_secret: SecretStr | None = None
    connectwise_timeout_seconds: float = Field(default=15, gt=0, le=120)

    connectwise_url: str | None = None
    connectwise_company_id: str | None = None
    connectwise_public_key: SecretStr | None = None
    connectwise_private_key: SecretStr | None = None
    connectwise_client_id: SecretStr | None = None

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = "knowledge_base"

    openai_api_key: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    """Read settings once per process; restart after changing the environment."""
    return Settings()

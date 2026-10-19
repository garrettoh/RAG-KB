"""Environment configuration; service credentials are optional during setup."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
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
    qdrant_mode: Literal["embedded", "remote"] = "embedded"
    qdrant_path: str = ".qdrant"
    qdrant_timeout_seconds: int = Field(default=15, gt=0, le=120)
    embedding_provider: Literal["hash", "fastembed"] = "hash"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dimension: int = Field(default=384, gt=0, le=8192)
    embedding_cache_dir: str = ".fastembed_cache"
    chunk_size: int = Field(default=1000, ge=32, le=10000)
    chunk_overlap: int = Field(default=150, ge=0, le=9999)

    openai_api_key: SecretStr | None = None
    draft_provider: Literal["local", "ollama", "openai"] = "local"
    draft_timeout_seconds: float = Field(default=30, gt=0, le=120)
    openai_draft_model: str = Field(default="gpt-4o-mini", min_length=1)
    ollama_base_url: str = "http://localhost:11434"
    ollama_draft_model: str = Field(default="llama3.2", min_length=1)

    @model_validator(mode="after")
    def validate_chunk_overlap(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size.")
        return self


@lru_cache
def get_settings() -> Settings:
    """Read settings once per process; restart after changing the environment."""
    return Settings()

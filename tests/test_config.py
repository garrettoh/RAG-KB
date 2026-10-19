import pytest
from pydantic import SecretStr


def test_defaults_allow_startup_without_service_credentials():
    from app.config import Settings

    settings = Settings(_env_file=None)
    assert settings.database_url == "sqlite:///./rag_kb.db"
    assert settings.qdrant_url == "http://localhost:6333"
    assert settings.qdrant_collection == "knowledge_base"
    for name in ("connectwise_url", "connectwise_company_id", "connectwise_public_key",
                 "connectwise_private_key", "connectwise_client_id", "qdrant_api_key", "openai_api_key"):
        assert getattr(settings, name) is None


def test_environment_overrides_dotenv_and_loads_all_service_settings(monkeypatch, tmp_path):
    from app.config import Settings

    dotenv = tmp_path / ".env"
    dotenv.write_text("DATABASE_URL=sqlite:///from-file.db\nQDRANT_COLLECTION=file_collection\nUNRELATED_KEY=ignored\n", encoding="utf-8")
    values = {
        "DATABASE_URL": "sqlite:///from-environment.db",
        "CONNECTWISE_URL": "https://cw.example.test",
        "CONNECTWISE_COMPANY_ID": "test-company",
        "CONNECTWISE_PUBLIC_KEY": "test-public",
        "CONNECTWISE_PRIVATE_KEY": "test-private",
        "CONNECTWISE_CLIENT_ID": "test-client",
        "QDRANT_URL": "http://qdrant.example.test:6333",
        "QDRANT_API_KEY": "test-qdrant",
        "OPENAI_API_KEY": "test-openai",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    settings = Settings(_env_file=dotenv)
    assert settings.qdrant_collection == "file_collection"
    for key, expected in values.items():
        actual = getattr(settings, key.lower())
        assert (actual.get_secret_value() if isinstance(actual, SecretStr) else actual) == expected


@pytest.mark.parametrize("field", [
    "connectwise_public_key", "connectwise_private_key", "connectwise_client_id",
    "qdrant_api_key", "openai_api_key",
])
def test_credentials_are_masked_in_repr_and_json(field):
    from app.config import Settings

    settings = Settings(**{field: "sensitive-example-value"}, _env_file=None)
    assert isinstance(getattr(settings, field), SecretStr)
    assert "sensitive-example-value" not in repr(settings)
    assert "sensitive-example-value" not in settings.model_dump_json()


def test_get_settings_is_cached_and_can_be_cleared(monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("QDRANT_COLLECTION", "first")
    first = get_settings()
    monkeypatch.setenv("QDRANT_COLLECTION", "second")
    assert get_settings() is first
    assert get_settings().qdrant_collection == "first"
    get_settings.cache_clear()
    assert get_settings().qdrant_collection == "second"

import sys

import pytest


SETTING_KEYS = (
    "DATABASE_URL", "CONNECTWISE_URL", "CONNECTWISE_COMPANY_ID",
    "CONNECTWISE_PUBLIC_KEY", "CONNECTWISE_PRIVATE_KEY", "CONNECTWISE_CLIENT_ID",
    "QDRANT_URL", "QDRANT_API_KEY", "QDRANT_COLLECTION", "OPENAI_API_KEY",
)


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    """Never read a developer's credentials or create a database in the repo."""
    for key in SETTING_KEYS:
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(key.lower(), raising=False)
    monkeypatch.chdir(tmp_path)
    yield
    config = sys.modules.get("app.config")
    if config is not None:
        config.get_settings.cache_clear()


@pytest.fixture
def db_engine(tmp_path):
    from app.database import Base, create_db_engine
    from app import models  # Register every table before creating the schema.

    engine = create_db_engine(f"sqlite:///{tmp_path / 'models.db'}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(db_engine):
    from sqlalchemy.orm import Session

    with Session(db_engine) as session:
        yield session


@pytest.fixture
def application(tmp_path):
    from app.config import Settings
    from app.main import create_app

    return create_app(Settings(database_url=f"sqlite:///{tmp_path / 'app.db'}", _env_file=None))

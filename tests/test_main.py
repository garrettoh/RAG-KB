from fastapi.testclient import TestClient
from sqlalchemy import inspect


def test_schema_is_created_at_lifespan_startup_not_app_creation(tmp_path):
    from app.config import Settings
    from app.main import create_app

    database_path = tmp_path / "startup.db"
    application = create_app(Settings(database_url=f"sqlite:///{database_path}", _env_file=None))
    assert not database_path.exists()
    with TestClient(application) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/health").json() == {"status": "ok"}
        assert set(inspect(application.state.engine).get_table_names()) == {
            "raw_tickets", "tenant_assets", "kb_drafts",
        }


def test_default_app_starts_without_external_credentials():
    from app.main import app

    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_in_memory_sqlite_is_shared_with_request_threads():
    from app.config import Settings
    from app.main import create_app
    from app.database import get_db
    from app.models import RawTicket
    from fastapi import Depends
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    application = create_app(Settings(database_url="sqlite:///:memory:", _env_file=None))

    @application.get("/ticket-count")
    def ticket_count(session: Session = Depends(get_db)):
        return {"count": session.scalar(select(func.count()).select_from(RawTicket))}

    with TestClient(application) as client:
        assert client.get("/ticket-count").json() == {"count": 0}

from fastapi.testclient import TestClient
from sqlalchemy import select


def test_demo_review_approve_search_and_shutdown(tmp_path, monkeypatch):
    from app.config import Settings
    from app.demo import seed_demo
    from app.main import create_app
    from app.models import KBDraft, RawTicket, TenantAsset
    from app.vector_db import get_app_store, search_knowledge_base
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'demo.db'}", qdrant_path=":memory:", _env_file=None,
                        draft_provider="openai", embedding_provider="fastembed")
    # CLI always uses synthetic source + local drafting, regardless of optional settings.
    seed_demo(settings)
    app = create_app(settings.model_copy(update={"embedding_provider": "hash"}))
    assert getattr(app.state, "vector_store", None) is None
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            assert len(session.scalars(select(RawTicket)).all()) == 3
            assert len(session.scalars(select(TenantAsset)).all()) == 2
            assert {d.status for d in session.scalars(select(KBDraft))} == {"pending_review"}
        before = client.get("/api/v1/kb/drafts").json()
        seed_demo(settings)
        assert client.get("/api/v1/kb/drafts").json() == before
        assert len(before) == 3
        assert client.get("/api/v1/kb/search", params={"query_str": "network toolbar"}).json() == []
        for row in before:
            assert client.get(f"/api/v1/kb/drafts/{row['article_id']}").json() == row
            for _ in range(2):
                response = client.post(f"/api/v1/kb/drafts/{row['article_id']}/approve")
                assert response.status_code == 200, response.text
                assert response.json()["status"] == "indexed"
        for tenant in (None, 101, 202):
            params = {"query_str": "network toolbar"}
            if tenant:
                params["tenant_id"] = tenant
            hits = client.get("/api/v1/kb/search", params=params).json()
            assert hits
            assert any(h["scope"] == "global" for h in hits)
            assert all(h["tenant_id"] in (None, tenant) for h in hits)
            if tenant:
                assert any(h["tenant_id"] == tenant for h in hits)
        assert search_knowledge_base("toolbar", application=app)
        store = get_app_store(app)
        assert get_app_store(app) is store
    assert store.closed


def test_kb_validation_and_auth(application):
    with TestClient(application) as client:
        for path in ("/api/v1/kb/drafts/0", "/api/v1/kb/drafts/-1", "/api/v1/kb/search?query_str=", "/api/v1/kb/search?query_str=%20", "/api/v1/kb/search?query_str=x&tenant_id=0", "/api/v1/kb/search?query_str=x&tenant_id=true", "/api/v1/kb/search?query_str=x&tenant_id=1.0"):
            assert client.get(path).status_code == 422
        assert client.get("/api/v1/kb/drafts/999").status_code == 404
        assert client.post("/api/v1/kb/drafts/999/approve").status_code == 404
        application.state.settings.demo_mode = False
        assert client.get("/api/v1/kb/drafts").status_code == 503
        from pydantic import SecretStr
        application.state.settings.management_token = SecretStr("synthetic-management")
        for path in ("/api/v1/kb/drafts", "/api/v1/kb/drafts/1", "/api/v1/kb/search?query_str=toolbar"):
            assert client.get(path).status_code == 401
        assert client.post("/api/v1/kb/drafts/1/approve").status_code == 401
        assert client.get("/api/v1/kb/drafts", headers={"Authorization": "Bearer synthetic-management"}).status_code == 200


def test_failed_lazy_store_approval_is_durable_retryable(application):
    from app.models import KBDraft
    from app.vector_db import VectorStoreError
    def fail(settings):
        raise VectorStoreError("Optional provider unavailable.")
    application.state.vector_store_factory = fail
    with TestClient(application) as client:
        with application.state.session_factory() as session:
            row = KBDraft(scope="global", category="software", title="Toolbar", summary="Restore toolbar.", markdown_steps="Enable toolbar.")
            session.add(row)
            session.commit()
            article_id = row.article_id
        assert client.post(f"/api/v1/kb/drafts/{article_id}/approve").status_code == 503
        assert client.get(f"/api/v1/kb/drafts/{article_id}").json()["status"] == "approved"
        del application.state.vector_store_factory
        assert client.post(f"/api/v1/kb/drafts/{article_id}/approve").json()["status"] == "indexed"


def test_no_import_or_health_initializes_vector_providers(application, monkeypatch):
    from app import vector_db
    def forbidden(*args, **kwargs):
        raise AssertionError("Provider initialized before retrieval")
    monkeypatch.setattr(vector_db, "QdrantClient", forbidden)
    monkeypatch.setattr(vector_db, "FastEmbedEmbedding", forbidden)
    with TestClient(application) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/kb/drafts").json() == []


def test_seed_cli_ignores_live_provider_configuration(tmp_path, monkeypatch):
    import os
    from pathlib import Path
    import subprocess
    import sys
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models import KBDraft
    env = os.environ.copy()
    env.update(DATABASE_URL=f"sqlite:///{tmp_path / 'cli.db'}", DEMO_MODE="false", DRAFT_PROVIDER="openai",
               EMBEDDING_PROVIDER="fastembed", QDRANT_MODE="remote", QDRANT_URL="https://never-called.invalid")
    result = subprocess.run([sys.executable, "-m", "app.demo"], cwd=Path(__file__).resolve().parents[1],
                            env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert "pending drafts seeded" in result.stdout
    engine = create_engine(env["DATABASE_URL"])
    with Session(engine) as session:
        rows = session.scalars(select(KBDraft)).all()
        assert len(rows) == 3
        assert {row.status for row in rows} == {"pending_review"}
        assert {(row.scope, row.target_tenant_id) for row in rows} == {("global", None), ("tenant", 101), ("tenant", 202)}
    engine.dispose()

import pytest
from qdrant_client import QdrantClient, models

from app.models import KBDraft


def draft(session, scope="global", tenant=None, status="approved", text="Enable the PDF toolbar."):
    row = KBDraft(scope=scope, target_tenant_id=tenant, category="software", title="PDF toolbar",
                  summary=text, markdown_steps=text, status=status)
    session.add(row)
    session.commit()
    return row


@pytest.fixture
def store():
    from app.vector_db import HashEmbedding, VectorStore
    result = VectorStore(QdrantClient(":memory:"), HashEmbedding(), "test", chunk_size=80, chunk_overlap=20)
    yield result
    result.close()


def test_review_gate_and_strict_tenant_results(session, store):
    from app.vector_db import index_article, search_knowledge_base
    pending = draft(session, status="pending_review")
    with pytest.raises(ValueError, match="approved"):
        index_article(session, pending, store)
    rows = [draft(session), draft(session, "tenant", 101), draft(session, "tenant", 202)]
    for row in rows:
        index_article(session, row, store)
    assert {r["article_id"] for r in search_knowledge_base("PDF toolbar", store=store, session=session)} == {rows[0].article_id}
    for tenant, row in zip((101, 202), rows[1:]):
        hits = search_knowledge_base("PDF toolbar", tenant, store=store, session=session)
        assert {r["article_id"] for r in hits} == {rows[0].article_id, row.article_id}


@pytest.mark.parametrize("tenant", [True, False, 0, -1, "101", 1.5])
def test_reject_invalid_tenant_before_embedding(session, store, tenant):
    from app.vector_db import search_knowledge_base
    with pytest.raises(ValueError, match="tenant"):
        search_knowledge_base("toolbar", tenant, store=store, session=session)


def test_replace_stale_chunks_and_repeat_index(session, store):
    from app.vector_db import index_article, search_knowledge_base
    row = draft(session, text="toolbar " * 80)
    index_article(session, row, store)
    points, _ = store.client.scroll("test", limit=100)
    assert len(points) > 2
    ids = {str(p.id) for p in points}
    index_article(session, row, store)
    assert {str(p.id) for p in store.client.scroll("test", limit=100)[0]} == ids
    row.summary = row.markdown_steps = "Short toolbar instructions."
    session.commit()
    assert search_knowledge_base("toolbar", store=store, session=session) == []
    index_article(session, row, store)
    assert len(store.client.scroll("test", limit=100)[0]) < len(points)


def test_failed_partial_write_is_not_visible_and_retry_recovers(session, store, monkeypatch):
    from app.vector_db import VectorStoreError, index_article, search_knowledge_base
    row = draft(session)
    index_article(session, row, store)
    original = store.client.upsert
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic secret upstream")
    monkeypatch.setattr(store.client, "upsert", fail)
    with pytest.raises(VectorStoreError, match="index"):
        index_article(session, row, store)
    assert row.status == "approved"
    assert search_knowledge_base("toolbar", store=store, session=session) == []
    monkeypatch.setattr(store.client, "upsert", original)
    index_article(session, row, store)
    assert row.status == "indexed"
    assert search_knowledge_base("toolbar", store=store, session=session)


@pytest.mark.parametrize("mutation", ["pending", "reassigned", "deleted"])
def test_sql_rechecks_returned_rows(session, store, mutation):
    from app.vector_db import index_article, search_knowledge_base
    row = draft(session, "tenant", 101)
    index_article(session, row, store)
    if mutation == "pending":
        row.status = "pending_review"
    elif mutation == "reassigned":
        row.target_tenant_id = 202
    else:
        session.delete(row)
    session.commit()
    assert search_knowledge_base("toolbar", 101, store=store, session=session) == []


def test_signature_rejects_same_dimension_other_provider_and_model():
    from app.vector_db import HashEmbedding, VectorStore, VectorStoreError
    client = QdrantClient(":memory:")
    first = VectorStore(client, HashEmbedding(), "test")
    class Other(HashEmbedding):
        provider = "other"
    with pytest.raises(VectorStoreError, match="signature"):
        VectorStore(client, Other(), "test")
    class OtherModel(HashEmbedding):
        model = "other"
    with pytest.raises(VectorStoreError, match="signature"):
        VectorStore(client, OtherModel(), "test")
    first.close()


def test_strict_filter_rejects_malformed_globals(session, store):
    from app.vector_db import index_article, search_knowledge_base
    row = draft(session)
    index_article(session, row, store)
    store.client.set_payload("test", {"tenant_id": 202}, points=models.Filter(must=[models.FieldCondition(key="article_id", match=models.MatchValue(value=row.article_id))]))
    assert search_knowledge_base("toolbar", store=store, session=session) == []
    assert search_knowledge_base("toolbar", 202, store=store, session=session) == []


def test_sanitizes_before_embedding_and_metadata(session, store):
    from app.vector_db import index_article, search_knowledge_base
    seen = []
    original = store.embedding.embed
    def capture(texts):
        seen.extend(texts)
        return original(texts)
    store.embedding.embed = capture
    row = draft(session, text="PDF password=supersecret at 10.2.3.4 jane@example.test")
    row.title = "PDF jane@example.test"
    row.category = "software jane@example.test"
    session.commit()
    index_article(session, row, store)
    search_knowledge_base("PDF password=supersecret 10.2.3.4", store=store, session=session)
    payloads = str([p.payload for p in store.client.scroll("test")[0]])
    for value in ("supersecret", "10.2.3.4", "jane@example.test"):
        assert value not in str(seen)
        assert value not in payloads


def test_chunk_overlap_and_deterministic_hash():
    from app.vector_db import HashEmbedding, chunk_text
    text = "abcdefghijklmnopqrstuvwxy"
    chunks = chunk_text(text, 10, 3)
    assert chunks == ["abcdefghij", "hijklmnopq", "opqrstuvwx", "vwxy"]
    assert HashEmbedding().embed(["PDF toolbar"]) == HashEmbedding().embed(["PDF toolbar"])
    with pytest.raises(ValueError):
        chunk_text(text, 5, 5)


def test_fastembed_adapter_genuine_model_boundary_and_failures(monkeypatch):
    import sys
    from types import SimpleNamespace
    from app.vector_db import FastEmbedEmbedding, VectorStoreError
    class Model:
        @classmethod
        def list_supported_models(cls):
            return [{"model": "test/model", "dim": 3}]
        def __init__(self, *, model_name, cache_dir):
            assert model_name == "test/model"
            assert cache_dir == "local-cache"
        def embed(self, texts):
            assert texts == ["sanitized procedure"]
            yield [0.1, 0.2, 0.3]
    monkeypatch.setitem(sys.modules, "fastembed", SimpleNamespace(TextEmbedding=Model))
    embedding = FastEmbedEmbedding("test/model", 3, "local-cache")
    assert embedding.embed(["sanitized procedure"]) == [[0.1, 0.2, 0.3]]
    for model, dimension in (("unknown", 3), ("test/model", 4)):
        with pytest.raises(VectorStoreError, match="model/dimension"):
            FastEmbedEmbedding(model, dimension, "local-cache")
    def fail(*args, **kwargs):
        raise RuntimeError("upstream-secret")
    monkeypatch.setattr(Model, "embed", fail)
    with pytest.raises(VectorStoreError, match="FastEmbed embedding failed"):
        embedding.embed(["sanitized procedure"])
    monkeypatch.setattr(Model, "__init__", fail)
    with pytest.raises(VectorStoreError, match="could not load"):
        FastEmbedEmbedding("test/model", 3, "local-cache")
    monkeypatch.setattr(Model, "list_supported_models", fail)
    with pytest.raises(VectorStoreError, match="supported models"):
        FastEmbedEmbedding("test/model", 3, "local-cache")


def test_fastembed_missing_extra_is_actionable(monkeypatch):
    import sys
    from app.vector_db import FastEmbedEmbedding, VectorStoreError
    monkeypatch.setitem(sys.modules, "fastembed", None)
    with pytest.raises(VectorStoreError, match=r"install .\[fastembed\]"):
        FastEmbedEmbedding("test/model", 3, "cache")


@pytest.mark.parametrize("vectors", [[], [[1.0]], [[float("nan")] * 384]])
def test_invalid_embedding_never_publishes(session, store, monkeypatch, vectors):
    from app.vector_db import VectorStoreError, index_article
    row = draft(session)
    monkeypatch.setattr(store.embedding, "embed", lambda texts: vectors)
    with pytest.raises(VectorStoreError):
        index_article(session, row, store)
    assert row.status == "approved"
    assert store.client.count("test").count == 0


def test_final_sql_commit_failure_keeps_vector_points_hidden(session, store):
    from sqlalchemy import event
    from app.vector_db import index_article, search_knowledge_base, VectorStoreError
    row = draft(session)
    def fail_indexed_commit(current):
        if row.status == "indexed":
            raise RuntimeError("simulated SQL failure")
    event.listen(session, "before_commit", fail_indexed_commit)
    with pytest.raises(VectorStoreError):
        index_article(session, row, store)
    event.remove(session, "before_commit", fail_indexed_commit)
    assert row.status == "approved"
    assert store.client.count("test").count > 0
    assert search_knowledge_base("toolbar", store=store, session=session) == []
    index_article(session, row, store)
    assert search_knowledge_base("toolbar", store=store, session=session)


def test_embedded_disk_store_is_lazy_thread_safe_and_reopens(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from app.config import Settings
    from app.vector_db import create_vector_store
    settings = Settings(qdrant_path=str(tmp_path / "vectors"), _env_file=None)
    store = create_vector_store(settings)
    with ThreadPoolExecutor(max_workers=1) as worker:
        assert worker.submit(store.client.count, "knowledge_base").result().count == 0
    store.close()
    second = create_vector_store(settings)
    assert second.client.count("knowledge_base").count == 0
    second.close()


def test_invalid_chunk_settings_fail_early():
    from pydantic import ValidationError
    from app.config import Settings
    with pytest.raises(ValidationError, match="overlap"):
        Settings(chunk_size=100, chunk_overlap=100, _env_file=None)

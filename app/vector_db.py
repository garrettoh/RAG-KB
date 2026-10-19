"""Lazy embedded/remote Qdrant, reviewed publication and SQL-verified retrieval.

No client or embedding model is created at import time. Publication commits an
approved checkpoint before touching Qdrant; a failed vector operation is retried
by approving again. SQL status/revision checks hide incomplete and stale points.
"""

from collections import Counter
from hashlib import sha256
import json
import math
import re
from threading import RLock
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient, models
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import KBDraft
from app.sanitizer import sanitize_text


class VectorStoreError(RuntimeError):
    """Actionable provider/storage failure without upstream secrets."""

    status_code = 503


class Embedding(Protocol):
    provider: str
    model: str
    dimension: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedding:
    """Stable normalized lexical feature hashing; no semantic model/download."""

    provider = "hash"
    model = "sha256-token-count-v1"

    def __init__(self, dimension: int = 384):
        if type(dimension) is not int or dimension <= 0:
            raise ValueError("Embedding dimension must be a positive integer.")
        self.dimension = dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = [0.0] * self.dimension
            for token, count in Counter(re.findall(r"\w+", text.casefold())).items():
                digest = sha256(token.encode("utf-8")).digest()
                vector[int.from_bytes(digest[:8], "big") % self.dimension] += count
            norm = math.sqrt(sum(value * value for value in vector))
            vectors.append([value / norm for value in vector] if norm else vector)
        return vectors


class FastEmbedEmbedding:
    """Optional genuine local model. Constructed only on explicit first use."""

    provider = "fastembed"

    def __init__(self, model: str, dimension: int, cache_dir: str):
        self.model, self.dimension = model, dimension
        try:
            from fastembed import TextEmbedding
        except ImportError:
            raise VectorStoreError("FastEmbed is optional; install .[fastembed] or select embedding_provider=hash.") from None
        try:
            supported = TextEmbedding.list_supported_models()
        except Exception:
            raise VectorStoreError("FastEmbed supported models could not be read; check the optional package installation.") from None
        match = next((item for item in supported if item["model"] == model), None)
        if match is None or match["dim"] != dimension:
            raise VectorStoreError("FastEmbed model/dimension is unsupported; configure matching model dimensions.")
        try:
            self._model = TextEmbedding(model_name=model, cache_dir=cache_dir)
        except Exception:
            raise VectorStoreError("FastEmbed model could not load; first use needs a model download or populated cache.") from None

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            return [list(map(float, vector)) for vector in self._model.embed(texts)]
        except Exception:
            raise VectorStoreError("FastEmbed embedding failed; check the configured local model.") from None


def validate_tenant(tenant_id: int | None) -> None:
    if tenant_id is not None and (type(tenant_id) is not int or tenant_id <= 0):
        raise ValueError("tenant_id must be a positive integer or None.")


def scope_filter(tenant_id: int | None) -> models.Filter:
    """Always applied inside Qdrant before ranking; no caller filter override."""
    validate_tenant(tenant_id)
    global_only = models.Filter(must=[
        models.FieldCondition(key="scope", match=models.MatchValue(value="global")),
        models.IsNullCondition(is_null=models.PayloadField(key="tenant_id")),
    ])
    if tenant_id is None:
        return global_only
    return models.Filter(should=[global_only, models.Filter(must=[
        models.FieldCondition(key="scope", match=models.MatchValue(value="tenant")),
        models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant_id)),
    ])])


def chunk_text(text: str, size: int = 1000, overlap: int = 150) -> list[str]:
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("Chunk overlap must be nonnegative and smaller than chunk size.")
    if not text:
        return []
    chunks = []
    for start in range(0, len(text), size - overlap):
        chunks.append(text[start:start + size])
        if start + size >= len(text):
            break
    return chunks


def article_content(row: KBDraft) -> dict:
    """Canonical sanitized content and scope for payloads and stale checks."""
    validate_tenant(row.target_tenant_id)
    if (row.scope == "global" and row.target_tenant_id is not None or
            row.scope == "tenant" and row.target_tenant_id is None or row.scope not in ("global", "tenant")):
        raise ValueError("Article scope and tenant target are inconsistent.")
    return dict(scope=row.scope, tenant_id=row.target_tenant_id,
                category=sanitize_text(row.category), title=sanitize_text(row.title),
                text=sanitize_text(f"{row.title}\n\n{row.summary}\n\n{row.markdown_steps}"))


def revision(content: dict) -> str:
    return sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


class VectorStore:
    """Owns one Qdrant collection/client; contains no mutable tenant state."""

    def __init__(self, client: QdrantClient, embedding: Embedding, collection: str,
                 *, chunk_size: int = 1000, chunk_overlap: int = 150):
        chunk_text("", chunk_size, chunk_overlap)
        self.client, self.embedding, self.collection = client, embedding, collection
        self.chunk_size, self.chunk_overlap = chunk_size, chunk_overlap
        self.lock = RLock()
        self.closed = False
        self.signature = json.dumps(dict(provider=embedding.provider, model=embedding.model,
                                         dimension=embedding.dimension), sort_keys=True)
        # The immutable named-vector schema persists the full signature identity,
        # even for empty collections and identical dimensions across providers.
        self.vector_name = "embedding_" + sha256(self.signature.encode()).hexdigest()
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        try:
            if not self.client.collection_exists(self.collection):
                self.client.create_collection(self.collection, vectors_config={self.vector_name:
                    models.VectorParams(size=self.embedding.dimension, distance=models.Distance.COSINE)})
            vectors = self.client.get_collection(self.collection).config.params.vectors
            if not isinstance(vectors, dict) or set(vectors) != {self.vector_name}:
                raise VectorStoreError("Collection embedding signature mismatch; use another collection or rebuild it.")
            if vectors[self.vector_name].size != self.embedding.dimension:
                raise VectorStoreError("Collection embedding signature dimension mismatch; rebuild the collection.")
        except VectorStoreError:
            raise
        except Exception:
            raise VectorStoreError("Qdrant collection unavailable; check local path or remote configuration.") from None

    def _embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self.embedding.embed([sanitize_text(text) for text in texts])
        if len(vectors) != len(texts) or any(len(v) != self.embedding.dimension or
                any(not math.isfinite(x) for x in v) for v in vectors):
            raise VectorStoreError("Embedding provider returned invalid vector dimensions or values.")
        return vectors

    def replace_article(self, row: KBDraft) -> None:
        if row.status not in ("approved", "indexed"):
            raise ValueError("Only approved articles may be indexed.")
        content = article_content(row)
        chunks = chunk_text(content["text"], self.chunk_size, self.chunk_overlap)
        with self.lock:
            self._ensure_collection()
            vectors = self._embed(chunks)
            points = [models.PointStruct(
                id=str(uuid5(NAMESPACE_URL, f"rag-kb:{self.collection}:{row.article_id}:{number}")),
                vector={self.vector_name: vector},
                payload={**content, "text": text, "article_id": row.article_id, "chunk_index": number,
                         "revision": revision(content), "embedding_signature": self.signature},
            ) for number, (text, vector) in enumerate(zip(chunks, vectors))]
            self.client.delete(self.collection, points_selector=models.FilterSelector(filter=models.Filter(must=[
                models.FieldCondition(key="article_id", match=models.MatchValue(value=row.article_id)),
            ])), wait=True)
            if points:
                self.client.upsert(self.collection, points=points, wait=True)

    def search(self, query_str: str, tenant_id: int | None, session: Session, limit: int = 10) -> list[dict]:
        validate_tenant(tenant_id)
        if not isinstance(query_str, str) or not query_str.strip() or len(query_str) > 4000:
            raise ValueError("query_str must contain 1 to 4000 characters.")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Search limit must be between 1 and 100.")
        with self.lock:
            try:
                self._ensure_collection()
                vector = self._embed([query_str])[0]
                points = self.client.query_points(self.collection, query=vector, using=self.vector_name,
                    query_filter=scope_filter(tenant_id), limit=limit, with_payload=True).points
            except VectorStoreError:
                raise
            except Exception:
                raise VectorStoreError("Knowledge search failed; check the vector store and embedding provider.") from None
            results = []
            for point in points:
                payload = point.payload or {}
                article_id = payload.get("article_id")
                if type(article_id) is not int:
                    continue
                # populate_existing ignores stale ORM identities in long-lived callers.
                row = session.scalar(select(KBDraft).where(KBDraft.article_id == article_id).execution_options(populate_existing=True))
                if row is None or row.status != "indexed":
                    continue
                try:
                    content = article_content(row)
                except ValueError:
                    continue
                allowed = (row.scope == "global" and row.target_tenant_id is None or
                           tenant_id is not None and row.scope == "tenant" and row.target_tenant_id == tenant_id)
                if (not allowed or payload.get("scope") != row.scope or payload.get("tenant_id") != row.target_tenant_id or
                        payload.get("revision") != revision(content) or payload.get("embedding_signature") != self.signature):
                    continue
                results.append({key: payload[key] for key in ("article_id", "scope", "tenant_id", "category", "title", "text")} | {"score": point.score})
            return results

    def close(self) -> None:
        with self.lock:
            if not self.closed:
                self.client.close()
                self.closed = True


def create_vector_store(settings: Settings) -> VectorStore:
    embedding = (HashEmbedding(settings.embedding_dimension) if settings.embedding_provider == "hash" else
                 FastEmbedEmbedding(settings.embedding_model, settings.embedding_dimension, settings.embedding_cache_dir))
    client = None
    try:
        if settings.qdrant_mode == "remote":
            client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key.get_secret_value()
                                  if settings.qdrant_api_key else None, timeout=settings.qdrant_timeout_seconds)
        elif settings.qdrant_path == ":memory:":
            client = QdrantClient(":memory:", force_disable_check_same_thread=True)
        else:
            client = QdrantClient(path=settings.qdrant_path, force_disable_check_same_thread=True)
        return VectorStore(client, embedding, settings.qdrant_collection,
                           chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
    except Exception as exc:
        if client is not None:
            client.close()
        if isinstance(exc, (VectorStoreError, ValueError)):
            raise
        raise VectorStoreError("Cannot open Qdrant; use a writable local path or check remote configuration.") from None


def get_app_store(application) -> VectorStore:
    with application.state.vector_store_lock:
        if application.state.vector_store is None:
            factory = getattr(application.state, "vector_store_factory", create_vector_store)
            application.state.vector_store = factory(application.state.settings)
        return application.state.vector_store


def index_article(session: Session, row: KBDraft, store: VectorStore) -> KBDraft:
    """Publish an already approved article; owns SQL checkpoint/final commits.

    A pending row cannot enter here. The review API commits approval first. An
    indexed row is temporarily approved so even partial vector writes stay hidden.
    """
    if row.status not in ("approved", "indexed"):
        raise ValueError("Only approved articles may be indexed.")
    with store.lock:
        row.status = "approved"
        session.commit()
        try:
            store.replace_article(row)
            row.status = "indexed"
            session.commit()
        except Exception:
            session.rollback()
            raise VectorStoreError("Knowledge indexing failed; article remains approved. Retry approval after fixing the provider/store.") from None
    return row


def search_knowledge_base(query_str: str, tenant_id: int | None = None, *, store: VectorStore | None = None,
                          session: Session | None = None, application=None, limit: int = 10) -> list[dict]:
    """Search explicit store/session or a configured app (default: app.main.app)."""
    validate_tenant(tenant_id)
    if store is not None and session is not None:
        return store.search(query_str, tenant_id, session, limit)
    if application is None:
        from app.main import app
        application = app
    store = store if store is not None else get_app_store(application)
    if session is not None:
        return store.search(query_str, tenant_id, session, limit)
    with application.state.session_factory() as owned_session:
        return store.search(query_str, tenant_id, owned_session, limit)

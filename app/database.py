"""SQLAlchemy engine and request-scoped synchronous sessions."""

from collections.abc import Generator

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def create_db_engine(database_url: str) -> Engine:
    """Create an engine without opening a connection or creating tables."""
    url = make_url(database_url)
    options = {}
    if url.get_backend_name() == "sqlite":
        # FastAPI runs synchronous dependencies and routes in worker threads.
        options["connect_args"] = {"check_same_thread": False}
        if url.database in (None, "", ":memory:"):
            options["poolclass"] = StaticPool
    return create_engine(url, **options)


engine = create_db_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, close_resets_only=False)


def get_db(request: Request) -> Generator[Session, None, None]:
    """Yield one session; callers explicitly commit writes they want to keep."""
    session = request.app.state.session_factory()
    try:
        yield session
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()

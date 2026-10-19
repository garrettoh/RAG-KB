"""FastAPI entry point; database initialization belongs to application startup."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker

from app import models  # Register model metadata before the lifespan creates tables.
from app.config import Settings, get_settings
from app.database import Base, SessionLocal, create_db_engine, engine
from app.api.webhooks import router as connectwise_router
from app.connectwise_client import IntegrationError
from app.ingestion import IngestionConflict


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an independent application when explicit settings are supplied."""
    selected_settings = settings if settings is not None else get_settings()
    db_engine = create_db_engine(settings.database_url) if settings is not None else engine
    session_factory = (
        sessionmaker(bind=db_engine, autoflush=False, close_resets_only=False)
        if settings is not None else SessionLocal
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            Base.metadata.create_all(bind=db_engine)
            yield
        finally:
            db_engine.dispose()

    application = FastAPI(title="RAG Knowledge Base", lifespan=lifespan)
    application.state.settings = selected_settings
    application.state.engine = db_engine
    application.state.session_factory = session_factory
    application.include_router(connectwise_router)

    @application.exception_handler(IntegrationError)
    async def integration_error(request, exc: IntegrationError):
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @application.exception_handler(IngestionConflict)
    async def ingestion_conflict(request, exc: IngestionConflict):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()

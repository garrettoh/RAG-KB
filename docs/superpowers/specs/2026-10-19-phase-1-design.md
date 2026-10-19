# Phase 1: project setup and database models

The user requests sequential implementation of a multi-tenant agentic knowledge base, using one specialist implementer per module and passing unit tests before progressing. This execution implements Phase 1 only, then authenticates with GitHub CLI and pushes to https://github.com/garrettoh/RAG-KB.

## Required behavior

- Initialize a FastAPI Python project with pydantic-settings configuration and SQLite/SQLAlchemy persistence.
- `config.py` loads ConnectWise credentials, Qdrant settings, and OpenAI API keys from the environment and optional `.env` files. Store sensitive values as `SecretStr` and omit real credentials from source control. Local startup must work without live service credentials.
- `database.py` provides a declarative base, SQLite engine, session factory, and FastAPI session dependency with reliable cleanup and rollback on errors.
- `RawTicket` stores ticket ID, company ID, summary, internal notes, resolution, and JSON raw payload.
- `TenantAsset` stores asset ID, company ID, asset name, serial number, type, and OS.
- `KBDraft` stores article ID, scope (`global`/`tenant`), target tenant ID, category, title, summary, markdown steps, and status (`pending_review`, `approved`, `indexed`). Default status is `pending_review`.
- Enforce valid scope/status values in SQLite. A global draft has no target tenant; a tenant draft requires a target tenant. Index tenant lookup columns.
- Include install/run instructions and tests that use isolated SQLite databases and no external services.

## Implementation choices

Use an `app` package, Python 3.13-compatible dependencies, synchronous SQLAlchemy 2 APIs, integer external ticket/asset/company IDs, and integer generated article IDs. Initialize tables explicitly during FastAPI lifespan rather than at import. Settings keys are unprefixed and documented in `.env.example`. Tests must cover settings defaults and overrides, secret masking, persistence of every required field, DB constraints, session closure/rollback, and application startup.

The local folder and remote are empty, so initialize a repository here; a separate worktree offers no existing work to isolate. Only Phase 1 is authorized for this execution. Later integrations and retrieval endpoints are out of scope.

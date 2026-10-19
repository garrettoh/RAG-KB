# RAG-KB

Phase 1 foundation for a multi-tenant knowledge base: FastAPI, environment
configuration, and SQLAlchemy 2 with SQLite. Python 3.13 or newer is required.

## Install and run

From the repository root in PowerShell:

```powershell
py -3.13 -m venv .venv
.venv/Scripts/python.exe -m pip install -e '.[dev]'
Copy-Item .env.example .env
.venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

On macOS/Linux, use `python3.13`, `.venv/bin/python`, and `cp` for the
equivalent commands. Creating `.env` is optional; defaults support local startup
without service credentials. Open <http://127.0.0.1:8000/health> to receive
`{"status":"ok"}`. API documentation is at <http://127.0.0.1:8000/docs>.

The app creates its three tables when its lifespan starts. Importing modules or
calling `create_app()` does not open a database or create tables. Startup is
idempotent for an existing schema. SQLite's parent directory must already exist.

## Configuration

`app/config.py` reads unprefixed environment variables and an optional UTF-8
`.env` file in the current working directory. Environment variables override
`.env`; empty values are ignored. Settings are cached per process, so restart
after changing configuration. `Settings(_env_file=...)` selects a different file;
`Settings(_env_file=None)` disables file loading.

| Variable | Default / purpose |
| --- | --- |
| `DATABASE_URL` | `sqlite:///./rag_kb.db`; relative to the launch directory |
| `CONNECTWISE_URL` | Optional ConnectWise Manage base URL |
| `CONNECTWISE_COMPANY_ID` | Optional ConnectWise login company identifier |
| `CONNECTWISE_PUBLIC_KEY` | Optional public API credential, masked as `SecretStr` |
| `CONNECTWISE_PRIVATE_KEY` | Optional private API credential, masked as `SecretStr` |
| `CONNECTWISE_CLIENT_ID` | Optional client credential, masked as `SecretStr` |
| `QDRANT_URL` | `http://localhost:6333` |
| `QDRANT_COLLECTION` | `knowledge_base` |
| `QDRANT_API_KEY` | Optional API credential, masked as `SecretStr` |
| `OPENAI_API_KEY` | Optional API credential, masked as `SecretStr` |

`.env`, SQLite files, caches, and virtual environments are ignored by git. Keep
real credentials out of source files. Service settings are loaded only; Phase 1
makes no ConnectWise, Qdrant, or OpenAI requests.

## Database and sessions

- `RawTicket`: integer external `ticket_id`, integer `company_id`, `summary`,
  `internal_notes`, `resolution`, and JSON `raw_payload`.
- `TenantAsset`: integer external `asset_id`, integer `company_id`, `asset_name`,
  `serial_number`, `type`, and `os`.
- `KBDraft`: generated integer `article_id`, `scope`, nullable `target_tenant_id`,
  `category`, `title`, `summary`, `markdown_steps`, and `status`.

SQLite enforces `scope` as `global` or `tenant` and `status` as `pending_review`,
`approved`, or `indexed`. New drafts default to `pending_review`, including direct
SQL inserts. Global drafts require a null target; tenant drafts require a target.
Company IDs and draft target tenant IDs are indexed. Fields are required except
`target_tenant_id`; tenant references are external identifiers without local
foreign keys. External ticket/asset IDs are unique primary keys.

`app/database.py` exports `Base`, `engine`, `SessionLocal`, and the FastAPI
`get_db` dependency. The dependency yields a session bound to the application's
engine, rolls back on errors, and always closes it. Callers must explicitly
`commit()` successful writes; finishing a request does not commit automatically.
A committed transaction cannot be undone by a later request error. Sessions must
not be reused after closure.

`create_app(Settings(database_url="sqlite:///..."))` creates an independently
configured app; its engine and session factory are available on `app.state`.
SQLite in-memory databases are supported across FastAPI request threads. Engines
are disposed during shutdown.

Schema creation uses `create_all`, which creates missing tables and does not
migrate existing tables. Schema migrations, service integrations, tenant
authorization, ingestion, retrieval, and article workflow APIs belong to later
phases. The health route reports application liveness.

## Tests

```powershell
.venv/Scripts/python.exe -m pytest -q
```

Tests use temporary SQLite databases and synthetic settings, with no live
credentials or external service calls. They cover settings precedence and secret
masking, every model field, database constraints and defaults, tenant indexes,
request session cleanup and rollback, lifespan table creation, and thread access
to in-memory SQLite. The Starlette dependency stays below 1.0 to retain
compatibility with HTTPX 0.x in the test client.

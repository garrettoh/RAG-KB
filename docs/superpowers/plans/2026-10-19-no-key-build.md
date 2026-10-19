# Credential-Free Knowledge Base Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development, sequential module tasks and tests before advancing.

**Goal:** Finish Phases 2–5 with a usable local workflow that needs no API keys and configurable live integrations.

**Architecture:** Keep existing FastAPI/SQLite foundation. Inject ConnectWise, drafting and vector providers via application settings; default to synthetic ingestion, deterministic local drafting, embedded Qdrant and local lexical embeddings. Sanitize before provider boundaries and enforce scope at both classification and retrieval.

**Tech Stack:** Python 3.13, FastAPI, httpx, Pydantic, SQLAlchemy, pytest, qdrant-client, optional FastEmbed/OpenAI.

**Spec:** `docs/superpowers/specs/2026-10-19-no-key-build-design.md`

## Global Constraints

- Keep all Phase 1 behavior/tests passing. No live credentials or remote services needed for defaults/tests.
- Implement phases sequentially with one specialist implementer per phase; run entire suite before next phase.
- No silent live-to-demo fallback. No raw secrets sent to model/vector providers. No automatic draft approval.
- Local demo is not a public authenticated multi-tenant service; live routes require configured secrets.
- No import-time network calls, model downloads, or Qdrant initialization.

## Review Focus

- Webhook retry and cross-company identifier conflicts must not corrupt tenant data.
- Redacted infrastructure details must retain tenant classification.
- Malformed/provider-controlled output must not route a draft to another tenant.
- Vector filtering and failed/repeated indexing must not reveal pending or other-tenant records.
- A clean key-free installation must support the documented demo without a remote server/model download.

### Task 1: Phase 2 — Integration Engineer

**Files:** `app/connectwise_client.py`, `app/ingestion.py`, `app/demo_data.py`, `app/api/webhooks.py`, `app/api/dependencies.py`, `app/config.py`, `app/main.py`, pyproject, README, tests.
**Produces:** async client `fetch_closed_tickets`, `fetch_ticket`, `fetch_time_entries`, `fetch_configurations`; demo equivalents; `ingest_ticket(session, client, ticket_id)` and `sync_company(session, client, company_id)`; protected webhook/sync routes. Preserve `get_db`.

- [x] Write failing tests with mocked httpx and real temporary SQLite: auth/header, pagination, errors, closure handling, time entry aggregation, replay, company conflicts, asset sync, and live webhook secret enforcement.
- [x] Implement all Phase 2 spec behavior with documented payload and interfaces; retain app lifecycle.
- [x] Run `.venv/Scripts/python.exe -m pytest -q`; review Phase 2, fix findings, commit module before Phase 3.

### Task 2: Phase 3 — Security Engineer

**Files:** `app/sanitizer.py`, `tests/test_sanitizer.py`, README.
**Produces:** `sanitize_text(text: str) -> str`, idempotent stable redaction markers.

- [x] Write failing parametrized tests for all spec secret/address/footer classes, code blocks, multiline signatures, URLs, JSON/YAML, embedded secrets, false positives, and idempotence.
- [x] Implement focused robust regex plus IP validation where useful; preserve resolution instructions and markdown structure.
- [x] Run full pytest; review/fix and commit before Phase 4.

### Task 3: Phase 4 — AI/ML Engineer

**Files:** `app/agent_processor.py`, `app/api/kb.py`, settings/app hooks, tests, README.
**Consumes:** RawTicket, KBDraft, get_db, sanitize_text, management auth.
**Produces:** KBDraftOutput schema and processor accepting injectable local/OpenAI provider; pending draft persistence and POST `/api/v1/kb/drafts/from-ticket/{ticket_id}`.

- [x] Write failing tests for generic vs tenant classification before scrubbing, missing resolution, malformed/provider-misdirected outputs, raw input/output secret scrubbing, pending status and mocked OpenAI failures.
- [x] Implement local extractive drafting, optional structured Ollama provider without API key, and optional structured OpenAI provider; local classifier overrides unsafe scope/tenant selections and persists all required output. Mock both remote transports in tests.
- [x] Run full pytest; review/fix and commit before Phase 5.

### Task 4: Phase 5 — RAG & Search Engineer

**Files:** `app/vector_db.py`, extend `app/api/kb.py`, `app/demo.py`, settings/main hooks, pyproject, .gitignore, README, tests.
**Consumes:** pending drafts from processor, sanitize_text, get_db, management auth.
**Produces:** chunk/index/search services; `search_knowledge_base(query_str, tenant_id=None)`; KB management endpoints; synthetic demo seed CLI.

- [x] Write failing tests using real embedded in-memory Qdrant: chunking, approved-only indexing, provider signature compatibility, global-only and tenant-specific filters, failed/repeated indexing, stale chunks, API validation, local no-key end-to-end seed/draft/approve/search.
- [x] Implement vector providers, local lexical embedding and optional FastEmbed, embedded/remote Qdrant, lifecycle and management routes; seed demo without auto approval.
- [x] Run full pytest and pip check; review/fix and commit.

### Completion

- [x] Whole-change review, resolve findings, rerun full tests on final code.
- [ ] Push to requested GitHub repository and verify matching remote/local hash.

## Validation record

| Gate | Full suite | Review |
| --- | --- | --- |
| Phase 2 | 69 passed | Approved |
| Phase 3 | 215 passed | Approved after redaction regression fixes |
| Phase 4 | 270 passed | Approved after scope/optional metadata regression fixes |
| Phase 5 / combined build | 299 passed | Whole-change and Phase 5 review approved, no material findings |

The suite emits one upstream Starlette/AnyIO deprecation warning. `pip check` reports no broken requirements. Editable installation succeeded. Tests use mocked service transports and real local SQLite/Qdrant; no API keys or model downloads.

An additional actual CLI/HTTP smoke run in temporary SQLite and disk-backed Qdrant seeded three pending drafts, explicitly reviewed/approved/indexed all three, and verified results: one global article with no tenant ID, two articles for tenant 101, two for tenant 202. Each tenant saw its own article plus the global article.

Defaults are deterministic extractive drafting and lexical vector hashing. Optional Ollama, OpenAI, FastEmbed, and live ConnectWise/remote Qdrant adapters are implemented; live model/service compatibility was not verified without credentials or model installations. See README for the local workflow and deployment limitations.

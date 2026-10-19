# RAG-KB

Multi-tenant knowledge base foundation with FastAPI, SQLAlchemy 2/SQLite,
and synthetic or live ConnectWise ingestion. Python 3.13 or newer is required.

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
| `DEMO_MODE` | `true`; use synthetic ConnectWise records without credentials |
| `MANAGEMENT_TOKEN` | Bearer token required by live management routes |
| `WEBHOOK_SECRET` | Separate shared secret required by the live webhook |
| `CONNECTWISE_TIMEOUT_SECONDS` | `15`; positive HTTP timeout, at most 120 seconds |
| `CONNECTWISE_URL` | Full HTTPS API root, e.g. `https://your-host/v4_6_release/apis/3.0` |
| `CONNECTWISE_COMPANY_ID` | Optional ConnectWise login company identifier |
| `CONNECTWISE_PUBLIC_KEY` | Optional public API credential, masked as `SecretStr` |
| `CONNECTWISE_PRIVATE_KEY` | Optional private API credential, masked as `SecretStr` |
| `CONNECTWISE_CLIENT_ID` | Optional client credential, masked as `SecretStr` |
| `QDRANT_MODE` | `embedded`; optional `remote` connects to `QDRANT_URL` |
| `QDRANT_PATH` | `.qdrant`; embedded storage directory, or `:memory:` |
| `QDRANT_URL` | `http://localhost:6333`; used only in remote mode |
| `QDRANT_COLLECTION` | `knowledge_base` |
| `QDRANT_API_KEY` | Optional API credential, masked as `SecretStr` |
| `QDRANT_TIMEOUT_SECONDS` | `15`; remote timeout, at most 120 seconds |
| `EMBEDDING_PROVIDER` | `hash`; optional `fastembed` needs the extra below |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5`; only used by FastEmbed |
| `EMBEDDING_DIMENSION` | `384`; must match the FastEmbed model when selected |
| `EMBEDDING_CACHE_DIR` | `.fastembed_cache`; optional model cache |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `1000` / `150` characters; overlap must be smaller than size |
| `OPENAI_API_KEY` | Optional API credential, masked as `SecretStr` |
| `DRAFT_PROVIDER` | `local`; deterministic extraction, or optional `ollama` / `openai` |
| `DRAFT_TIMEOUT_SECONDS` | `30`; positive HTTP timeout, at most 120 seconds |
| `OLLAMA_BASE_URL` | `http://localhost:11434`; user-managed Ollama server |
| `OLLAMA_DRAFT_MODEL` | `llama3.2`; must already be installed in your Ollama server |
| `OPENAI_DRAFT_MODEL` | `gpt-4o-mini`; configurable structured-output compatible model |

`.env`, SQLite files, caches, and virtual environments are ignored by git. Keep
real credentials out of source files. Default demo operation makes no remote
requests. Qdrant and OpenAI are not initialized by ingestion.

## ConnectWise ingestion

Run the app using the installation command above. Default `DEMO_MODE=true`
provides two entirely synthetic companies: Example Orchard (`101`, ticket
`1001`) and Example Harbor (`202`, ticket `2001`). No API keys, downloads or
external servers are required. In PowerShell, ingest a ticket and sync each
company's closed tickets and configurations:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/webhooks/connectwise -ContentType 'application/json' -Body '{"ticket_id":1001}'
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/connectwise/sync/101
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/connectwise/sync/202
```

The webhook's JSON contract is exactly `{"ticket_id":1001}`: a positive integer
with no extra fields. A ConnectWise callback relay must translate its native
notification into this documented payload; native callback bodies are not
accepted directly. The event is only a notification: ingestion fetches the
authoritative ticket and time entries and requires `closedFlag` to be the JSON
boolean `true`. An open ticket returns `{"status":"ignored","ticket_id":...}`;
a stored ticket returns `{"status":"ingested","ticket_id":...}`. Event-provided
company IDs or claimed resolutions are not accepted. Invalid payloads return
422. A replay updates the same row. External ticket/configuration IDs cannot
move between companies; collisions return 409. A failed company sync rolls back
its entire database transaction. Sync counts describe processed records, so a
repeat sync reports the same counts while updating existing rows.

`RawTicket.raw_payload` retains both `ticket` and `time_entries` unchanged.
Internal analysis includes the ticket's `internalAnalysis`, time-entry
`internalNotes`, and notes marked `addToInternalAnalysisFlag=true`. Resolution
includes the ticket's `resolution` and notes marked
`addToResolutionFlag=true`. Other notes remain in the raw payload. Ingestion
stores raw source content in SQLite; access to this database must be restricted.
Ingestion does not create or approve KB drafts.

For live operation set `DEMO_MODE=false`, configure all five `CONNECTWISE_*`
credentials/root settings above, plus independent `WEBHOOK_SECRET` and
`MANAGEMENT_TOKEN`. The client uses Basic authentication with username
`<login-company>+<public-key>`, private key as password, and a `clientId` header.
The login company string is distinct from numeric customer company IDs.
Authorized live operations fail with 503 if credentials are missing; live
failures never switch to synthetic records. HTTP failures return 502, and
connectivity/timeout failures return 503, without upstream response bodies or
credential-bearing URLs. Requests use bounded timeouts and pagination; redirects
are rejected. Clients are closed after each request.

```powershell
$hookHeaders = @{ 'X-Webhook-Secret' = $env:WEBHOOK_SECRET }
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/webhooks/connectwise -Headers $hookHeaders -ContentType 'application/json' -Body '{"ticket_id":12345}'
$managementHeaders = @{ Authorization = "Bearer $env:MANAGEMENT_TOKEN" }
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/connectwise/sync/101 -Headers $managementHeaders
```

Live routes reject missing/incorrect secrets with 401 and deny access with 503
when their required secret is unconfigured. Demo routes bypass authentication
and are intended for local development. A management token grants management
access; supplied customer IDs do not establish end-user tenant authorization.
Deployment identity and tenant authorization remain a separate concern.

The live adapter reads `service/tickets`, `service/tickets/{id}`, `time/entries`
and `company/configurations`, with `conditions`, `page`, `pageSize`, and stable
`orderBy=id asc`. Verify these fields and member permissions against your PSA
version before live deployment. ConnectWise's official
[REST reference](https://developer.connectwise.com/Products/ConnectWise_PSA/REST)
and [authentication guide](https://developer.connectwise.com/Products/Manage/Developer_Guide/Authentication)
require developer sign-in; no live credentials were available to certify a
deployment. Transport behavior follows the official HTTPX
[async client](https://www.python-httpx.org/async/) and
[timeout](https://www.python-httpx.org/advanced/timeouts/) documentation.

Python integration interfaces are `ConnectWiseClient(settings, transport=...)`
and `DemoConnectWiseClient()`, both exposing async `fetch_closed_tickets(company_id=None)`,
`fetch_ticket(ticket_id)`, `fetch_time_entries(ticket_id)`,
`fetch_configurations(company_id)`, and `aclose()`. Both support `async with`.
`ingest_ticket(session, client, ticket_id)` returns `RawTicket | None`;
`sync_company(session, client, company_id)` returns ticket/asset counts. Services
flush writes; callers own commit/rollback. API dependencies expose
`get_app_settings`, `get_connectwise_client`, `require_management_auth`, and
`require_webhook_auth`; `get_db` remains in `app.database`. For a custom adapter,
set `application.state.connectwise_client_factory = lambda settings: adapter`;
the request dependency owns closing that adapter.

## Text sanitization

`app.sanitizer.sanitize_text(text: str) -> str` is a deterministic, local text
filter. It replaces recognized values with stable markers such as
`[REDACTED_IP]`, `[REDACTED_PASSWORD]`, `[REDACTED_API_KEY]`,
`[REDACTED_TOKEN]`, `[REDACTED_MAC]`, `[REDACTED_SERIAL]`,
`[REDACTED_EMAIL]`, `[REDACTED_CREDENTIALS]`, and `[REDACTED_SIGNATURE]`.
Repeated processing preserves those markers. It retains markdown, code fences,
and surrounding procedure content while redacting inside code examples too.

Rules cover validated IPv4/IPv6 (including compressed, bracketed, scoped and
IPv4-mapped forms), common MAC formats, labeled passwords/API keys/tokens/hardware
serials in assignments, JSON, YAML and command options, bearer tokens, common
OpenAI/GitHub/AWS/Slack key prefixes, URL credentials and sensitive query values,
and email addresses. Quoted multiline values and indented YAML block scalars are
supported. Short terminal contact signatures, mobile signature lines and explicit
confidentiality paragraphs are recognized conservatively; uncertain prose stays.

This is a practical redaction layer, **not exhaustive PII or secret prevention**.
Unlabeled or obfuscated credentials, encoded/escaped field names, unusual key
formats, unquoted secrets containing whitespace, names, phone numbers outside
recognized signatures, hostnames, company identifiers and unfamiliar signatures
can remain. A valid four-part dotted number can be indistinguishable from an IP
address. Contextual heuristics can still produce false positives or false
negatives. Review generated content before sharing, and restrict access to raw
SQLite tickets, which remain unchanged. Sanitization does not establish tenant
authorization or change a document's tenant sensitivity. This phase exposes the
filter; drafting calls it before provider requests and again on provider output.

## Knowledge drafts

After ingesting a synthetic ticket, generate a reviewable draft:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/kb/drafts/from-ticket/2001
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/kb/drafts/from-ticket/1001
```

The response includes `article_id`, scope/target, category, title, summary,
`markdown_steps` and `status=pending_review`. A missing stored ticket returns
404; invalid IDs return 422. Live mode requires the management bearer header
shown above. Each call creates a new draft for review; it never approves or
publishes an article. Affected hardware/software appears in a dedicated markdown
section without changing the database schema.

The default `DRAFT_PROVIDER=local` is **deterministic extraction, not an LLM**.
It takes actual resolution steps from the stored ticket, extracts known product
and hardware terms, and marks an absent resolution as requiring review instead
of inventing a fix. It makes no network requests or model downloads and requires
no API key. Classification uses original ticket prose locally before redaction:
IP addresses, recognizable hostnames, local infrastructure and known company
context stay tenant scoped. Generic software issues can be global. Detection is
heuristic and requires review. Company metadata alone does not force a generic
ticket into tenant scope. All tenant drafts target the source company; provider
output cannot select another company or downgrade locally detected sensitivity.

For an actual local LLM, install/run Ollama yourself and install your chosen model,
then set `DRAFT_PROVIDER=ollama`, `OLLAMA_DRAFT_MODEL` and optionally
`OLLAMA_BASE_URL`. This app never installs or downloads models. The adapter sends
`POST /api/chat` with `stream=false`, the JSON schema in `format`, and a bounded
timeout. Missing server/model and malformed responses return actionable 502/503
errors. See Ollama's official [structured output guide](https://docs.ollama.com/capabilities/structured-outputs)
and [chat endpoint](https://docs.ollama.com/api/chat).

For optional cloud drafting, set `DRAFT_PROVIDER=openai`, `OPENAI_API_KEY` and a
compatible `OPENAI_DRAFT_MODEL`. The HTTPX adapter uses Chat Completions with a
strict JSON schema and validates responses with Pydantic. Missing keys return
503; refusals, malformed output and upstream failures return 502/503 without
exposing remote response bodies. See the official OpenAI Docs
[structured outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs).
Neither optional provider silently falls back to local extraction.

Only sanitized summary, internal notes and resolution are sent to model providers;
the raw payload is never sent. Known source company names/identifiers from
company metadata are replaced with `[REDACTED_COMPANY]`. Model output is sanitized
again before persistence. The prompt treats ticket content as untrusted data;
this does not guarantee immunity to prompt injection or unsupported model claims.
Unknown company names/hostnames and other unrecognized sensitive text can remain
as described above. Review every draft before sharing or publishing.

Python interfaces in `app.agent_processor` are `KBDraftOutput`, `DraftInput`,
`LocalDraftProvider()`, `OllamaDraftProvider(settings, transport=...)`,
`OpenAIDraftProvider(settings, transport=...)`, `create_draft_provider(settings)`,
and async `process_ticket(session, raw_ticket, provider) -> KBDraft`. Providers
expose async `generate(sanitized_input)` and `aclose()`. The processor flushes;
the caller commits or rolls back. Set `application.state.draft_provider_factory`
to inject a provider; the route dependency closes it after success or failure.

## Local review and search demo

This workflow needs no API key, Qdrant server, LLM, or model download. From the
repository root, run these commands in the first PowerShell terminal. Setting
these values explicitly also overrides optional providers in your `.env`:

```powershell
$env:DEMO_MODE = 'true'
$env:DRAFT_PROVIDER = 'local'
$env:EMBEDDING_PROVIDER = 'hash'
$env:EMBEDDING_DIMENSION = '384'
$env:QDRANT_MODE = 'embedded'
.venv/Scripts/python.exe -m app.demo
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The seed command stores three synthetic tickets and three **pending** drafts:
Orchard network (`1001`, tenant `101`), Harbor network (`2002`, tenant `202`), and
the generic PDF toolbar (`2001`, global), plus two synthetic assets. It always
uses synthetic ingestion and local extraction, even if optional live source,
drafting, or embedding providers are configured. It never calls a model/vector
provider or approves content. Repeating the command preserves existing demo
drafts, including their review status. The older ingestion fixtures remain two
tickets; `2002` is added by this CLI only.

In a second PowerShell terminal, list and inspect each complete draft:

```powershell
$kbBase = 'http://127.0.0.1:8000/api/v1/kb'
$drafts = Invoke-RestMethod "$kbBase/drafts"
$drafts | Format-Table article_id, title, scope, target_tenant_id, status
$globalDraft = $drafts | Where-Object title -eq 'Synthetic demo ticket 2001'
$orchardDraft = $drafts | Where-Object title -eq 'Synthetic demo ticket 1001'
$harborDraft = $drafts | Where-Object title -eq 'Synthetic demo ticket 2002'
Invoke-RestMethod "$kbBase/drafts/$($globalDraft.article_id)" | Format-List *
Invoke-RestMethod "$kbBase/drafts/$($orchardDraft.article_id)" | Format-List *
Invoke-RestMethod "$kbBase/drafts/$($harborDraft.article_id)" | Format-List *
# Fresh pending drafts are absent from search:
Invoke-RestMethod "$kbBase/search?query_str=network%20toolbar&tenant_id=101"
```

After reviewing the scope, title, summary, and steps, explicitly approve each
article you want published. Approval indexes the article immediately:

```powershell
Invoke-RestMethod -Method Post "$kbBase/drafts/$($globalDraft.article_id)/approve"
Invoke-RestMethod -Method Post "$kbBase/drafts/$($orchardDraft.article_id)/approve"
Invoke-RestMethod -Method Post "$kbBase/drafts/$($harborDraft.article_id)/approve"
# Global PDF content only:
Invoke-RestMethod "$kbBase/search?query_str=network%20toolbar" | Format-Table article_id, scope, tenant_id, title
# Global PDF content plus Orchard's network article; no Harbor article:
Invoke-RestMethod "$kbBase/search?query_str=network%20toolbar&tenant_id=101" | Format-Table article_id, scope, tenant_id, title
# Global PDF content plus Harbor's network article; no Orchard article:
Invoke-RestMethod "$kbBase/search?query_str=network%20toolbar&tenant_id=202" | Format-Table article_id, scope, tenant_id, title
```

The same protected management API supports `GET /drafts?limit=100&offset=0`,
`GET /drafts/{article_id}`, `POST /drafts/{article_id}/approve`, and
`GET /search?query_str=...&tenant_id=101&limit=10`. IDs must be positive integers;
search requires nonblank text of at most 4000 characters. Search returns ranked
chunks with article ID, scope, tenant ID, sanitized category/title/text and score.
One article can return several chunks. Extra caller parameters cannot override
the internal scope filter. Live mode requires the management bearer header on
all these routes. Selecting a tenant ID is a retrieval filter; deployment code
must separately authorize which tenant a caller may select.

The default hash embedding uses normalized lexical token counts in deterministic
hash buckets. It is a useful zero-download local fallback, not a learned semantic
model: synonyms may fail to match, collisions can affect rank, and a ranked result
does not guarantee relevance. Search retrieves content, without generating an
LLM answer. Local extraction and hash search both work without keys. Optional
Ollama drafting requires a running server and an installed model; optional OpenAI
drafting requires a key. Neither silently falls back when selected and failing.

For genuine local semantic embeddings, install the optional package and select a
supported model and matching dimension:

```powershell
.venv/Scripts/python.exe -m pip install -e '.[fastembed]'
$env:EMBEDDING_PROVIDER = 'fastembed'
$env:EMBEDDING_MODEL = 'BAAI/bge-small-en-v1.5'
$env:EMBEDDING_DIMENSION = '384'
$env:QDRANT_COLLECTION = 'knowledge_base_fastembed'
```

FastEmbed loads only when search/indexing first needs it; first use can download
model weights. It requires network access or an already populated cache. No model
is installed/downloaded by the default workflow or tests. The adapter follows
the official [FastEmbed usage](https://qdrant.github.io/fastembed/). Set
`QDRANT_MODE=remote`, `QDRANT_URL`, and optionally `QDRANT_API_KEY` for a separate
Qdrant service. Remote requests include sanitized chunks/metadata or sanitized
query vectors; IDs and scope metadata remain necessary for isolation.

Embedded Qdrant is a real on-disk vector store. Use one application process per
storage path (do not use multiple Uvicorn workers with that path). The app lazily
caches one client/model per app, serializes local operations across worker
threads, and closes the client on shutdown. Collection schemas encode a hash of
provider, model and dimension in an immutable named-vector key; incompatible
collections are rejected, including different providers with equal dimensions.
Choose a new collection and explicitly approve existing articles again to rebuild
when changing embedding settings. Existing collections without this signature
are also rejected.

Before indexing, all content and textual metadata are sanitized again. Documents
are chunked with overlap and stable article/chunk IDs; reindexing removes old
chunks. Qdrant filters before ranking: `scope=global AND tenant_id=null`, plus
`scope=tenant AND tenant_id=<exact requested ID>` only when supplied. The design
uses Qdrant's official [filter conditions](https://qdrant.tech/documentation/search/filtering/).
Every returned chunk is checked against current SQL status, scope/target and a
sanitized content revision; pending, deleted, reassigned or changed SQL records
are hidden. Sanitization has the limitations listed above and raw source tickets
remain in SQLite.

SQL and Qdrant do not share an atomic transaction. Approval first commits
`approved`, then replaces vectors, then commits `indexed` only after vector
success. A vector/model failure or final SQL failure leaves the durable approved
checkpoint for retry; partial or old points are hidden by SQL checks. A crash
between these steps can likewise leave an approved article. Repeat the approval
request after correcting configuration/storage to replace all its chunks and
finish indexing. This is idempotent for the same content and does not add SQL
drafts. Stale hidden chunks may consume ranking slots until reindexed; restore
or rebuild vector storage if its files are lost. Review approval is a deliberate
management action, never a side effect of drafting or seeding.

Python entry points are `VectorStore(client, embedding, collection)`,
`HashEmbedding(dimension=384)`, `FastEmbedEmbedding(model, dimension, cache_dir)`,
`create_vector_store(settings)`, `get_app_store(application)`,
`index_article(session, approved_draft, store)`, and
`search_knowledge_base(query_str, tenant_id=None, *, store=None, session=None,
application=None, limit=10)`. The public search callable accepts an explicit
store/session or uses the selected app's lazy store/session factory; omitting
the app uses `app.main.app`. No tenant/filter is stored globally. Indexing owns
its SQL checkpoint/final commits; don't bundle unrelated pending SQL writes in
the same session. A direct pending draft is rejected by the indexing service.
Inject `application.state.vector_store_factory` or `application.state.vector_store`
for custom application setup; the app owns shutdown cleanup.

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
migrate existing tables. Schema migrations and deployment tenant authorization
remain separate work. The health route reports application
liveness.

## Tests

```powershell
.venv/Scripts/python.exe -m pytest -q
```

Tests use temporary SQLite databases and synthetic settings, with no live
credentials or external service calls. They cover settings precedence and secret
masking, every model field, database constraints and defaults, tenant indexes,
request session cleanup and rollback, lifespan table creation, and thread access
to in-memory SQLite, plus ConnectWise authentication, pagination, failure handling,
ingestion replay, company isolation, configuration sync, and live route secrets.
Remote client tests use `httpx.MockTransport`. The Starlette dependency stays
below 1.0 to retain compatibility with HTTPX 0.x in the test client.
Retrieval/workflow tests use real embedded Qdrant and hash embeddings, including
isolation, review gating, stale/failed indexing and retries, model signatures,
shutdown, and a no-key CLI/HTTP review workflow. FastEmbed model behavior is mocked
at the optional package boundary, so tests never download model weights.

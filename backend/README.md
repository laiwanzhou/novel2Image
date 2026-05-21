# Novel Character Visualization Backend

FastAPI + CLI backend for the first-stage novel character visualization MVP.

The MVP source of truth is PostgreSQL + pgvector. It supports the offline loop:

```text
local novel import
-> chapter storage
-> paragraph chunks
-> fake embeddings / pgvector persistence
-> reviewable character knowledge
-> confirmed time-ranged CharacterState
-> evidence-backed prompt generation
```

## Scope

Implemented in this phase:

- TXT and Markdown import.
- EPUB fails clearly and is reserved for a later adapter.
- PostgreSQL models and Alembic migration.
- pgvector-backed chunk embedding persistence.
- Character and alias candidate review.
- Chapter-level fake LLM extraction for candidate events and state changes.
- Initial CharacterState and state-change synthesis.
- Prompt generation with saved state/event/chunk evidence.
- Minimal FastAPI routes for review, state inspection, and prompt generation.
- Novel Workspace APIs for one-stop MVP operation from the thin admin UI.

Not implemented in this phase:

- Crawlers or site-specific scraping.
- Qdrant.
- Neo4j.
- Celery / Redis task orchestration.
- Group prompts.
- User accounts, permissions, or collaboration.
- Mandatory image generation API integration.

## Setup

Install dependencies in the backend virtual environment:

```powershell
cd backend
.\.venv\Scripts\python -m pip install -e ".[dev]"
```

Runtime settings use `NOVEL_VIS_` environment variables. Defaults:

```text
NOVEL_VIS_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/novel_visualization
NOVEL_VIS_TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:55432/novel_visualization_test
NOVEL_VIS_EMBEDDING_PROVIDER=fake
NOVEL_VIS_LLM_PROVIDER=fake
```

## PostgreSQL + pgvector

For local testing, run a pgvector-enabled Postgres on port `55432`:

```powershell
docker run --name novel-vis-pgvector-test `
  -e POSTGRES_PASSWORD=postgres `
  -e POSTGRES_DB=novel_visualization_test `
  -p 55432:5432 `
  -d registry.cn-hangzhou.aliyuncs.com/fastgpt/pgvector:0.8.0-pg15
```

The test fixture rebuilds the `public` schema for each `pg_session`, creates the `vector` extension, and then creates tables from SQLAlchemy metadata. If Postgres is unavailable, integration tests using `pg_session` are skipped.

For the runtime database on port `5432`, create a database named `novel_visualization`, then run:

```powershell
cd backend
.\.venv\Scripts\python -m alembic upgrade head
```

## Run Backend

```powershell
cd backend
.\.venv\Scripts\python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

Health check:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health
```

## CLI Flow

All commands should be run from `backend/`.

Import a local Markdown or TXT novel:

```powershell
.\.venv\Scripts\python -m app.cli.main import-book --path ..\samples\book.md --title "Sample"
```

Chunk imported chapters:

```powershell
.\.venv\Scripts\python -m app.cli.main chunk-book --novel-id <novel_id>
```

Generate fake embeddings for chunks:

```powershell
.\.venv\Scripts\python -m app.cli.main embed-book --novel-id <novel_id>
```

Run fake chapter extraction:

```powershell
.\.venv\Scripts\python -m app.cli.main extract-chapter --chapter-id <chapter_id>
```

Review character candidates:

```powershell
.\.venv\Scripts\python -m app.cli.main list-character-candidates --novel-id <novel_id>
.\.venv\Scripts\python -m app.cli.main confirm-character --character-id <character_id> --reviewer cli
.\.venv\Scripts\python -m app.cli.main confirm-alias --alias-id <alias_id> --character-id <character_id> --reviewer cli
.\.venv\Scripts\python -m app.cli.main reject-candidate --target-type character --target-id <candidate_id> --reviewer cli
```

Generate a prompt for a confirmed character state:

```powershell
.\.venv\Scripts\python -m app.cli.main generate-prompt --novel-id <novel_id> --chapter-index 1 --character-id <character_id>
```

Prompt generation requires a confirmed `CharacterState` covering the requested chapter.

## API Routes

Review:

```text
GET  /review/candidates?novel_id=<novel_id>
POST /review/{target_type}/{target_id}/accept
POST /review/{target_type}/{target_id}/reject
POST /review/aliases/{alias_id}/confirm
```

States:

```text
GET  /characters/{character_id}/states
POST /characters/{character_id}/initial-state
POST /states/{state_id}/confirm
```

Prompts:

```text
POST /prompts/generate
GET  /prompts/history?novel_id=<novel_id>
GET  /prompts/{prompt_generation_id}
```

`ValueError` responses are mapped to HTTP `400` with `{"detail": "..."}`.

## Novel Workspace APIs

Read-only workspace queries:

```text
GET /novels/{novel_id}
GET /novels/{novel_id}/chapters
GET /chapters/{chapter_id}/chunks
GET /novels/{novel_id}/processing-status
GET /novels/{novel_id}/characters?status=confirmed
```

Small synchronous workspace operations:

```text
POST /novels/{novel_id}/chunk
POST /novels/{novel_id}/embed
POST /chapters/{chapter_id}/extract
POST /states/{state_id}/confirm
```

`POST /novels/{novel_id}/chunk` replaces stored chunks, so the Workspace blocks it after chunk-based knowledge or prompt records exist for that novel. This prevents invalidating evidence IDs referenced by character/alias candidates, events, state changes, states, prompt records, and saved evidence snapshots.

If a novel already has chunk-based knowledge or prompt records, the route returns HTTP `400`. Use the CLI/database rebuild flow or a future dedicated rebuild workflow if the source text must be rechunked.

## Verification

Run backend tests and lint:

```powershell
cd backend
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m ruff check app tests alembic
```

Run migration SQL generation:

```powershell
.\.venv\Scripts\python -m alembic upgrade head --sql
```

Current expected baseline:

```text
72 passed
ruff: All checks passed
```

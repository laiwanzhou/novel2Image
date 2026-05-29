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

- Product crawler integration. A site-specific operator crawler exists under `backend/scripts/` for manual validation only; it writes local files and is not connected to FastAPI, Workspace, or the database.
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
NOVEL_VIS_LLM_API_BASE=
NOVEL_VIS_LLM_API_KEY=
NOVEL_VIS_LLM_MODEL=
NOVEL_VIS_LLM_JSON_MODE=true
NOVEL_VIS_LLM_MAX_TOKENS=4096
NOVEL_VIS_LLM_TIMEOUT_SECONDS=180
NOVEL_VIS_EXTRACTION_AUTO_CONFIRM_EVENTS=false
```

Copy the root `.env.example` to `.env` for local overrides. Do not commit `.env`.

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

With the default `NOVEL_VIS_LLM_PROVIDER=fake`, extraction returns deterministic empty candidate lists unless tests inject a fake response.
By default, extracted `CharacterEvent` records and `CharacterStateChange` records are both saved as `candidate`.
For long-form operator runs where events are treated as an audit log, use `--auto-confirm-events` or set `NOVEL_VIS_EXTRACTION_AUTO_CONFIRM_EVENTS=true`.
This only auto-confirms `CharacterEvent`; `CharacterStateChange` remains `candidate`, and no `CharacterState` is synthesized automatically.

To use an OpenAI-compatible FastGPT workflow instead:

```powershell
$env:NOVEL_VIS_LLM_PROVIDER="fastgpt"
$env:NOVEL_VIS_LLM_API_BASE="https://api.deepseek.com"
$env:NOVEL_VIS_LLM_API_KEY="<your-api-key>"
$env:NOVEL_VIS_LLM_MODEL="deepseek-v4-pro"
$env:NOVEL_VIS_LLM_JSON_MODE="true"
$env:NOVEL_VIS_LLM_MAX_TOKENS="4096"
$env:NOVEL_VIS_LLM_TIMEOUT_SECONDS="180"
.\.venv\Scripts\python -m app.cli.main extract-chapter --chapter-id <chapter_id>
```

The same provider setting is used by the Workspace "extract selected chapter" action (`POST /chapters/{chapter_id}/extract`).

The FastGPT provider calls the OpenAI-compatible chat completions endpoint:

```text
POST {NOVEL_VIS_LLM_API_BASE}/v1/chat/completions
```

When `NOVEL_VIS_LLM_JSON_MODE=true`, the request body includes:

```json
{
  "response_format": {
    "type": "json_object"
  }
}
```

`NOVEL_VIS_LLM_MAX_TOKENS` is also sent as `max_tokens`. For DeepSeek JSON Output, keep JSON mode enabled and keep the prompt's explicit `json` instructions and output example. JSON mode does not replace backend validation: empty content, non-JSON content, truncated JSON, missing schema fields, missing chunk evidence, or invalid IDs still fail with `ValueError`.

Expected model output is strict JSON:

```json
{
  "events": [
    {
      "character_id": "confirmed-character-uuid",
      "character_name": "optional display name",
      "chapter_index": 1,
      "event_summary": "what happened",
      "event_type": "identity",
      "is_long_term_change": true,
      "affected_fields": ["identity"],
      "source_chunk_ids": ["chunk-uuid"],
      "confidence": 0.8,
      "explanation": "why the evidence supports this"
    }
  ],
  "state_changes": [
    {
      "character_id": "confirmed-character-uuid",
      "character_name": "optional display name",
      "event_index": 0,
      "changed_fields": [
        {
          "field": "identity",
          "before": "old value",
          "after": "new value",
          "source_chunk_ids": ["chunk-uuid"],
          "confidence": 0.8
        }
      ],
      "source_chunk_ids": ["chunk-uuid"],
      "confidence": 0.8,
      "explanation": "why the field changed"
    }
  ]
}
```

Extraction remains review-first:

- LLM output creates candidate `CharacterEvent` and candidate `CharacterStateChange` by default.
- If `NOVEL_VIS_EXTRACTION_AUTO_CONFIRM_EVENTS=true` or CLI `--auto-confirm-events` is used, only `CharacterEvent` is saved as `confirmed` with reviewer `auto-extraction`.
- `CharacterStateChange` always remains `candidate` and requires review.
- It does not create or confirm `CharacterState`.
- It does not bypass manual review.
- `character_id` must reference an existing confirmed character.
- `event_type` must be one of `appearance`, `identity`, `relationship`, `motivation`, or `other`.
- Every event, state change, and changed field must include non-empty `source_chunk_ids` from the current chapter.

Common extraction errors:

- Missing `NOVEL_VIS_LLM_API_KEY`, `NOVEL_VIS_LLM_API_BASE`, or `NOVEL_VIS_LLM_MODEL`.
- JSON mode responses with empty content.
- Model returns prose instead of JSON.
- Model wraps invalid JSON in a code fence.
- Model omits top-level `events` or `state_changes`.
- Model omits `source_chunk_ids`.
- Model references chunks outside the selected chapter.
- Model references a character that has not been confirmed yet.
- Model returns an unsupported `event_type` such as `decision` or `encounter`; this is rejected before persistence to protect the review data, not a database failure.

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

## Operator Preview Sample

`GET /operator/crawled-novel-preview` defaults to a small committed sample under:

```text
backend/data/samples/crawled-novel/
```

This keeps clone-and-test reproducible without committing real crawled novel text. To point the operator preview at a local crawler output directory, set:

```powershell
$env:NOVEL_VIS_CRAWLED_PREVIEW_DIR="D:\path\to\crawler-output"
```

The directory must contain `novel.md` and `manifest.json`.

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
105 passed
ruff: All checks passed
```

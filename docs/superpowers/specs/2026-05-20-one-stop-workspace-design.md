# Novel Workspace One-stop Page Design

Date: 2026-05-20

## Goal

Build a one-stop operation page named **Novel Workspace** for the completed phase 1 MVP.

The page should make the existing MVP easier to use from the browser by gathering the common workflow around one `novel_id`:

```text
select novel
-> inspect chapter / chunk / embedding status
-> run small synchronous processing actions
-> review character and alias candidates
-> inspect and confirm CharacterState records
-> generate a chapter-specific single-character prompt
-> inspect prompt warnings and evidence snapshot
```

This is an ergonomics layer over the existing Postgres-centered modular monolith. It does not change the phase 1 data ownership model: PostgreSQL + pgvector remains the source of truth, and generation still depends on confirmed CharacterState / CharacterEvent / chunk evidence.

## Recommended Architecture

Use option B: **add a few thin backend APIs plus one frontend Novel Workspace page**.

```text
Novel Workspace page
  -> existing and new thin FastAPI routes
  -> existing service layer
  -> existing repository layer
  -> PostgreSQL + pgvector
```

The backend routes must remain orchestration-thin:

- Routes parse request parameters and return JSON.
- Routes instantiate repositories/services using the current dependency pattern.
- Routes do not duplicate chunking, embedding, extraction, state lifecycle, review, or prompt-generation business rules.
- Reusable response shaping can live in route helpers or lightweight schemas.

The frontend remains a thin operational page:

- It calls API endpoints and displays returned records.
- It does not implement state confirmation rules, evidence filtering rules, or prompt-generation rules.
- It keeps the current `Review`, `States`, and `Prompts` pages available.
- `Novel Workspace` becomes the default opened tab because it is the preferred daily workflow surface.

## Scope

### In Scope

- Add a `Novel Workspace` tab/page.
- Start the workspace from a user-entered `novel_id`.
- Show lightweight novel metadata.
- List lightweight chapter summaries.
- List chunks for a selected chapter.
- Show processing status counts.
- Run synchronous `chunk novel`.
- Run synchronous `embed novel`.
- Run synchronous `extract single chapter`.
- Show character and alias candidates through existing review data.
- Accept/reject character candidates and confirm aliases through existing review APIs.
- List confirmed characters for prompt selection.
- Show a selected character's CharacterState timeline.
- Create an initial CharacterState candidate through the existing API.
- Confirm a candidate CharacterState through a new thin API.
- Generate a prompt for one `chapter_index + character_id`.
- Display `final_prompt`, `negative_prompt`, `warnings`, and `evidence_snapshot`.

### Non-goals

This round does not include:

- Browser file upload.
- Import API.
- Crawlers.
- Full-book extraction from the browser.
- Task queue, job table, cancellation, retry, or progress tracking.
- Celery or Redis.
- Qdrant.
- Neo4j.
- Group prompts.
- Real image generation API.
- Real FastGPT integration.
- FastGPT configuration UI or API key input.
- Auth, permissions, collaboration, or a complete product dashboard.

Local import remains a CLI/operator workflow. The browser starts from an existing `novel_id`.

## Existing APIs To Reuse

These routes already exist and should be reused by the workspace:

```text
GET  /review/candidates?novel_id=<novel_id>
POST /review/{target_type}/{target_id}/accept
POST /review/{target_type}/{target_id}/reject
POST /review/aliases/{alias_id}/confirm

GET  /characters/{character_id}/states
POST /characters/{character_id}/initial-state

POST /prompts/generate
GET  /prompts/history?novel_id=<novel_id>
GET  /prompts/{prompt_generation_id}
```

## New Backend APIs

### Get Novel Metadata

```text
GET /novels/{novel_id}
```

Response:

```json
{
  "id": "uuid",
  "title": "Novel title",
  "author": "Author name",
  "source_type": "markdown",
  "language": "zh",
  "imported_at": "2026-05-20T00:00:00Z",
  "created_at": "2026-05-20T00:00:00Z"
}
```

The response does not include chapter content.

### List Chapters

```text
GET /novels/{novel_id}/chapters
```

Response:

```json
[
  {
    "id": "uuid",
    "title": "第一章 初见",
    "chapter_index": 1,
    "word_count": 1320,
    "chunk_count": 2,
    "embedded_count": 2
  }
]
```

This endpoint returns lightweight summary fields only. It must not return `chapter.content`.

### List Chapter Chunks

```text
GET /chapters/{chapter_id}/chunks
```

Response:

```json
[
  {
    "id": "uuid",
    "novel_id": "uuid",
    "chapter_id": "uuid",
    "chapter_index": 1,
    "chunk_index": 1,
    "char_count": 900,
    "token_count": 900,
    "has_embedding": true,
    "text_preview": "前 240 个字符预览..."
  }
]
```

The workspace only needs previews for inspection and evidence selection. It should not fetch a whole book's source text through this API.

### Processing Status

```text
GET /novels/{novel_id}/processing-status
```

Response:

```json
{
  "novel_id": "uuid",
  "chapter_count": 30,
  "chunk_count": 82,
  "embedded_count": 82,
  "missing_embedding_count": 0,
  "candidate_character_count": 4,
  "confirmed_character_count": 2,
  "candidate_alias_count": 3,
  "candidate_event_count": 5,
  "candidate_state_change_count": 2,
  "candidate_state_count": 2,
  "confirmed_state_count": 3,
  "prompt_generation_count": 6
}
```

The status endpoint is a summary endpoint only. It reports counts from existing tables and does not start work.

### Chunk Novel

```text
POST /novels/{novel_id}/chunk
```

Request:

```json
{
  "target_chars": 1200,
  "max_chars": 1500
}
```

Response:

```json
{
  "novel_id": "uuid",
  "chapter_count": 30,
  "chunk_count": 82,
  "replaced_existing_chunks": true
}
```

This route calls the existing `ChunkingService` and `ChunkRepository.replace_chunks_for_chapter()` for stored chapters. It is synchronous and intended for small MVP validation datasets. It does not expose task progress.

Because the current chunking path replaces chunk rows, it can invalidate existing evidence references. This Workspace API is allowed only before the novel has downstream knowledge.

Downstream knowledge includes:

- `CharacterEvent`;
- `CharacterStateChange`;
- `CharacterState`;
- `PromptGeneration`;
- chunk-evidence-dependent `Character` candidates;
- chunk-evidence-dependent `CharacterAlias` candidates.

If downstream knowledge exists for the novel, the API must return HTTP 400.

Error detail:

```json
{
  "detail": "This novel already has chunk-based knowledge or prompt records. Workspace chunk rebuild is blocked; use a CLI/database rebuild flow or a future dedicated rebuild workflow."
}
```

This round does not implement evidence migration, cascading cleanup, a rebuild workflow, or a task queue.

### Embed Novel

```text
POST /novels/{novel_id}/embed
```

Request:

```json
{
  "batch_size": 64
}
```

Response:

```json
{
  "novel_id": "uuid",
  "embedded_count": 82,
  "remaining_missing_embedding_count": 0,
  "provider": "fake"
}
```

This route calls `EmbeddingService.embed_missing_chunks()` with the configured embedding provider. In this phase the provider remains the existing fake provider unless the runtime is already configured differently outside this page.

### Extract Single Chapter

```text
POST /chapters/{chapter_id}/extract
```

Request:

```json
{}
```

Response:

```json
{
  "chapter_id": "uuid",
  "chapter_index": 3,
  "event_candidate_count": 1,
  "state_change_candidate_count": 1
}
```

This route calls `ExtractionService.extract_chapter_candidates(chapter_id)`. It is single-chapter and synchronous. It does not add a browser action for extracting all chapters.

### Confirm CharacterState

```text
POST /states/{state_id}/confirm
```

Request:

```json
{
  "reviewer": "admin",
  "note": "Looks correct"
}
```

Response:

```json
{
  "id": "uuid",
  "novel_id": "uuid",
  "character_id": "uuid",
  "chapter_start": 3,
  "chapter_end": null,
  "status": "confirmed",
  "reviewed_by": "admin",
  "review_note": "Looks correct"
}
```

This route calls `StateService.confirm_state()`. It must preserve the existing transactional lifecycle rules:

- only candidate states can be confirmed;
- confirming a new state closes the previous confirmed state range;
- confirmed ranges for the same novel and character must not overlap;
- failures return HTTP 400 through the existing `ValueError` handler.

### List Characters

```text
GET /novels/{novel_id}/characters?status=confirmed
```

Allowed status values:

```text
candidate
confirmed
rejected
all
```

Response:

```json
[
  {
    "id": "uuid",
    "novel_id": "uuid",
    "canonical_name": "林青",
    "status": "confirmed",
    "description": "Main character",
    "confidence": 0.93
  }
]
```

The workspace uses `status=confirmed` for Prompt Lab character selection. Candidate and rejected views can support review convenience, but prompt generation still uses backend confirmed-state checks.

## Frontend Novel Workspace Design

### Navigation

Current tabs:

```text
Review / States / Prompts
```

New tabs:

```text
Workspace / Review / States / Prompts
```

`Workspace` is the default tab. Existing pages remain available for focused inspection and debugging.

### Workspace State

The page has one top-level context:

```text
novel_id
```

Derived selections:

```text
selected chapter
selected character
selected candidate
selected state
selected prompt
```

The page should keep user-entered IDs in local component state. It does not need routing, account state, or persistent browser storage.

### Section 1: Novel Overview

Purpose:

- Enter and load `novel_id`.
- Show novel metadata.
- Show processing counts.
- Show a compact chapter table.

Actions:

- `Load Workspace`
- select one chapter row
- refresh status

Uses:

- `GET /novels/{novel_id}`
- `GET /novels/{novel_id}/processing-status`
- `GET /novels/{novel_id}/chapters`

### Section 2: Chapter And Processing

Purpose:

- Inspect selected chapter chunk status.
- Run small synchronous processing operations.

Actions:

- `Chunk Novel`
- `Embed Missing Chunks`
- `Extract Selected Chapter`
- `Load Selected Chapter Chunks`

Uses:

- `POST /novels/{novel_id}/chunk`
- `POST /novels/{novel_id}/embed`
- `POST /chapters/{chapter_id}/extract`
- `GET /chapters/{chapter_id}/chunks`

UI behavior:

- Buttons show loading state while a request is active.
- After success, refresh processing status and chapter summaries.
- Extraction success should refresh candidate review data.
- Errors are shown inline as API error messages.

### Section 3: Candidate Review

Purpose:

- Surface character/alias candidates inside the same workspace.
- Keep detailed review page available for deeper use.

Actions:

- accept character candidate;
- reject character or alias candidate;
- confirm alias by selecting or entering a confirmed character ID.

Uses existing:

- `GET /review/candidates?novel_id=<novel_id>`
- `POST /review/{target_type}/{target_id}/accept`
- `POST /review/{target_type}/{target_id}/reject`
- `POST /review/aliases/{alias_id}/confirm`
- `GET /novels/{novel_id}/characters?status=confirmed`

The workspace can show a compact candidate list. The existing `Review` page remains the fuller table-oriented page.

### Section 4: Character State Timeline

Purpose:

- Select a confirmed character.
- Inspect all states for that character.
- Create an initial candidate state when no confirmed state exists.
- Confirm candidate states.

Actions:

- load state timeline;
- create initial state candidate;
- confirm candidate state.

Uses:

- `GET /novels/{novel_id}/characters?status=confirmed`
- `GET /characters/{character_id}/states`
- `POST /characters/{character_id}/initial-state`
- `POST /states/{state_id}/confirm`

The page should show enough fields to understand state ranges:

- `chapter_start`;
- `chapter_end`;
- `status`;
- `identity`;
- `appearance`;
- `visual_keywords`;
- `source_chunk_ids`.

State confirmation remains controlled by `StateService.confirm_state()` on the backend.

### Section 5: Prompt Lab

Purpose:

- Generate and inspect a single-character prompt for a chosen chapter and confirmed character.

Inputs:

- selected `chapter_index`;
- selected `character_id`;
- optional user request.

Actions:

- generate prompt;
- load prompt history;
- inspect prompt detail.

Uses:

- `POST /prompts/generate`
- `GET /prompts/history?novel_id=<novel_id>`
- `GET /prompts/{prompt_generation_id}`

Display:

- `final_prompt`;
- `negative_prompt`;
- `warnings`;
- `used_event_ids`;
- `used_chunk_ids`;
- `evidence_snapshot`.

If no confirmed CharacterState covers the selected chapter, the backend returns HTTP 400 and the UI shows the message. The frontend should not attempt to generate a prompt from candidate states.

## Relationship To Existing Pages

`Novel Workspace` is the default daily workflow page. It combines the common path across several existing pages.

The existing pages remain:

- `Review`: focused candidate review and alias confirmation.
- `States`: focused state timeline and initial-state form by character ID.
- `Prompts`: focused prompt history and prompt detail inspection.

The workspace should reuse shared API client functions where practical, but it may add workspace-specific helpers for the new novel/chapter/status endpoints.

## Error Handling

Backend:

- Continue mapping `ValueError` to HTTP 400 with `{"detail": "..."}`.
- Return 400 for unsupported status filters or invalid operation inputs.
- Return 400 for missing novel/chapter/state records under the current MVP convention.
- Do not add a broad exception handler that hides unexpected errors.

Frontend:

- Show request errors inline inside the relevant workspace section.
- Disable operation buttons while the related request is running.
- Refresh affected data after successful mutation.
- Do not silently ignore partial failures.

Synchronous processing routes should be presented as small local operations. If a request is slow on a larger book, the UI can show a loading state and the operator can continue using CLI for larger runs.

## Testing Scope

Backend tests:

- novel metadata endpoint returns lightweight fields and excludes chapter content;
- chapter list returns chunk and embedded counts;
- chapter chunks endpoint returns previews and `has_embedding`;
- processing status reports expected counts;
- chunk endpoint returns 400 when downstream knowledge already exists;
- chunk endpoint can generate or replace chunks when no downstream knowledge exists;
- chunk endpoint calls existing chunking path and returns counts;
- embed endpoint calls existing embedding path and returns counts;
- single-chapter extraction endpoint persists candidate counts through `ExtractionService`;
- confirm-state endpoint confirms a candidate through `StateService.confirm_state()`;
- character list endpoint filters by `candidate`, `confirmed`, `rejected`, and `all`;
- route tests verify business rules remain in services, with route tests asserting observable outcomes.

Frontend verification:

- TypeScript build passes.
- API client types cover new endpoint responses.
- `Novel Workspace` renders as default tab.
- Loading a workspace calls novel metadata, processing status, chapters, candidates, characters, and prompt history.
- Mutating actions refresh the relevant section.
- Prompt detail displays prompt, warnings, and evidence snapshot.

No test should require a real external LLM, FastGPT, Qdrant, Neo4j, Celery, crawler, or image generation API.

## FastGPT Future Provider Boundary

FastGPT is a future provider integration, not part of this workspace implementation.

The safe future integration point is the existing LLM provider boundary:

```text
FastGptLlmProvider implements LlmProvider.generate_json(...)
```

That provider may call a local FastGPT workflow to produce structured extraction output. The output must still pass through `ExtractionService` validation and be persisted as candidate `CharacterEvent` / `CharacterStateChange` rows in PostgreSQL.

FastGPT must not replace:

- PostgreSQL as the source of truth;
- confirmed CharacterState records;
- confirmed CharacterEvent records;
- chunk evidence;
- prompt generation evidence snapshots;
- review lifecycle rules.

This round does not add:

- FastGPT API key input;
- FastGPT workflow ID input;
- FastGPT settings page;
- provider switching UI.

A later spec can add provider configuration after the Novel Workspace API and page are stable.

## Self-Review

### Placeholder Check

The spec contains no open placeholders or unfinished requirement markers.

### Scope Check

The spec keeps the work to a one-stop MVP operations page plus thin APIs. It does not add Qdrant, Neo4j, Celery, crawlers, group prompts, a full Web product, image generation, upload, or import APIs.

### FastGPT Check

FastGPT is described only as a future provider behind the existing `LlmProvider` boundary. This round does not implement FastGPT integration or configuration UI.

### Operation Boundary Check

Browser-triggered processing is limited to synchronous chunking, embedding missing chunks, and extracting one selected chapter. Full-book extraction and task queues remain out of scope.

### Data Boundary Check

The new chapter and chunk endpoints return lightweight summaries and previews. They do not send whole-book text to the browser.

### Service Boundary Check

All new backend APIs are defined as route-level access to existing services and repositories. Business logic remains in `ChunkingService`, `EmbeddingService`, `ExtractionService`, `StateService`, `CharacterService`, `PromptGenerationService`, and repository methods.

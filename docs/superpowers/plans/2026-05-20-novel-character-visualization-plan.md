# Novel Character Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first-stage MVP that imports a local novel, chunks and embeds it, extracts reviewable character knowledge, confirms time-ranged CharacterState records, and generates chapter-specific image prompts with evidence chains.

**Architecture:** Use a Postgres-centered modular monolith. FastAPI, CLI commands, and the minimal React admin page all call the same Python service layer; PostgreSQL + pgvector is the only source of truth in MVP. Qdrant, Neo4j, Celery, crawlers, group prompts, and full image generation remain future scope.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.x, Alembic, Typer, Pydantic, PostgreSQL + pgvector, pytest, React + Vite + TypeScript.

---

## File Structure

Create the backend under `backend/` and the admin UI under `frontend/`.

```text
backend/
  pyproject.toml
  alembic.ini
  alembic/
    env.py
    versions/
  app/
    __init__.py
    api/
      __init__.py
      main.py
      routes/
        review.py
        prompts.py
        states.py
    cli/
      __init__.py
      main.py
    core/
      __init__.py
      config.py
      db.py
      enums.py
    models/
      __init__.py
      base.py
      novel.py
      character.py
      state.py
      prompt.py
    schemas/
      __init__.py
      import_schema.py
      review_schema.py
      prompt_schema.py
    repositories/
      __init__.py
      novels.py
      chunks.py
      characters.py
      states.py
      prompts.py
    services/
      __init__.py
      import_service.py
      chunking_service.py
      embedding_service.py
      retrieval_service.py
      character_service.py
      extraction_service.py
      state_service.py
      review_service.py
      evidence_service.py
      prompt_generation_service.py
    providers/
      __init__.py
      embeddings.py
      llm.py
  tests/
    conftest.py
    test_chunking_service.py
    test_import_service.py
    test_state_service.py
    test_prompt_generation_service.py
    test_review_service.py
    test_retrieval_service.py

frontend/
  package.json
  index.html
  src/
    main.tsx
    api.ts
    pages/
      CandidateReviewPage.tsx
      CharacterStatesPage.tsx
      PromptHistoryPage.tsx
```

Implementation should keep files focused. If a task starts making a service large, split private helper functions into the same module first; do not introduce extra architecture packages until a real duplication appears.

## Task 1: Backend Skeleton And Test Harness

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/core/config.py`
- Create: `backend/app/core/db.py`
- Create: `backend/app/core/enums.py`
- Create: `backend/app/api/main.py`
- Create: `backend/app/cli/main.py`
- Create: `backend/tests/conftest.py`

- [x] **Step 1: Create package skeleton**

Create empty `__init__.py` files in every backend package listed in the file structure.

- [x] **Step 2: Define dependencies**

`backend/pyproject.toml` should include runtime dependencies for FastAPI, SQLAlchemy, Alembic, Typer, Pydantic settings, psycopg, pgvector, and pytest.

```toml
[project]
name = "novel-character-visualization"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "alembic>=1.13",
  "fastapi>=0.110",
  "pgvector>=0.2",
  "psycopg[binary]>=3.1",
  "pydantic>=2.6",
  "pydantic-settings>=2.2",
  "sqlalchemy>=2.0",
  "typer>=0.12",
  "uvicorn>=0.29"
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.23",
  "ruff>=0.4"
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

- [x] **Step 3: Add config and DB session helpers**

Define `Settings` with `database_url`, `embedding_provider`, and `llm_provider`. Define a SQLAlchemy engine/session factory in `db.py`.

- [x] **Step 4: Add shared enums**

Define string enums for `ReviewStatus`, `PromptType`, `AliasType`, and `EventType`. `PromptType` must include only `character` and `scene` for MVP.

- [x] **Step 5: Add smoke tests**

`backend/tests/conftest.py` should provide a local SQLAlchemy test session fixture that can later be pointed at a test database.

- [x] **Step 6: Verify**

Run:

```powershell
cd backend
python -m pytest -q
```

Expected: pytest starts successfully and reports either collected smoke tests passing or no application import errors.

**Acceptance Criteria:**
- Backend imports without errors.
- `PromptType` does not include `group`.
- CLI and FastAPI entrypoints exist but do not implement product behavior yet.

## Task 2: Database Models And Migrations

**Files:**
- Create: `backend/app/models/base.py`
- Create: `backend/app/models/novel.py`
- Create: `backend/app/models/character.py`
- Create: `backend/app/models/state.py`
- Create: `backend/app/models/prompt.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/versions/0001_initial_schema.py`
- Test: `backend/tests/test_state_service.py`

- [x] **Step 1: Write schema tests first**

Add tests that assert the model metadata contains these tables:

```python
EXPECTED_TABLES = {
    "novels",
    "chapters",
    "chapter_chunks",
    "characters",
    "character_aliases",
    "character_events",
    "character_state_changes",
    "character_states",
    "prompt_generations",
    "generated_images",
    "review_actions",
}
```

- [x] **Step 2: Implement SQLAlchemy models**

Implement tables from the spec. Use JSON columns for `source_chunk_ids`, `changed_fields_json`, `metadata_json`, `warnings_json`, and `evidence_snapshot_json`. Use pgvector for `chapter_chunks.embedding`.

- [x] **Step 3: Add key indexes**

Add indexes for:

```text
chapters(novel_id, chapter_index)
chapter_chunks(novel_id, chapter_id, chunk_index)
characters(novel_id, status)
character_aliases(novel_id, alias_text, status)
character_events(novel_id, character_id, chapter_index, status)
character_states(novel_id, character_id, chapter_start, chapter_end, status)
prompt_generations(novel_id, chapter_index, character_id)
```

- [x] **Step 4: Add initial migration**

Migration must enable the `vector` extension before creating vector columns.

- [x] **Step 5: Verify**

Run:

```powershell
cd backend
python -m pytest tests/test_state_service.py -q
```

Expected: schema metadata tests pass.

**Acceptance Criteria:**
- All MVP tables exist.
- `prompt_generations.prompt_type` supports `character` and `scene`.
- No schema requires Qdrant, Neo4j, Celery, crawlers, or group prompts.

## Task 3: Import Adapters And Chapter Storage

**Files:**
- Create: `backend/app/schemas/import_schema.py`
- Create: `backend/app/services/import_service.py`
- Create: `backend/app/repositories/novels.py`
- Modify: `backend/app/cli/main.py`
- Test: `backend/tests/test_import_service.py`

- [x] **Step 1: Write import tests**

Test that TXT and Markdown inputs become a `BookManifest` with ordered `ChapterInput` records. Include a sample with two chapters:

```text
第1章 初见
第一章正文

第2章 转折
第二章正文
```

Expected chapter indexes are `1` and `2`.

- [x] **Step 2: Define schemas**

Create Pydantic models:

```python
class ChapterInput(BaseModel):
    chapter_index: int
    title: str
    content: str
    source_path: str | None = None
    word_count: int
    checksum: str

class BookManifest(BaseModel):
    title: str
    author: str | None = None
    source_type: Literal["txt", "markdown", "epub", "manifest"]
    language: str = "zh"
    chapters: list[ChapterInput]
```

- [x] **Step 3: Implement TXT and Markdown parsing**

Implement regex-based chapter boundary detection for common Chinese chapter headings. If no headings are found, create one chapter with `chapter_index = 1`.

- [x] **Step 4: Persist novel and chapters**

`NovelRepository` should insert one novel and many chapters in one transaction.

- [x] **Step 5: Add CLI command**

Add:

```powershell
python -m app.cli.main import-book --path <path> --title <title>
```

- [x] **Step 6: Verify**

Run:

```powershell
cd backend
python -m pytest tests/test_import_service.py -q
```

Expected: TXT and Markdown import tests pass.

**Acceptance Criteria:**
- Local TXT and Markdown import work.
- EPUB remains a later adapter inside the same ImportService boundary.
- Import produces normalized chapters without running extraction.

## Task 4: Paragraph-Preserving Chunking

**Files:**
- Create: `backend/app/services/chunking_service.py`
- Create: `backend/app/repositories/chunks.py`
- Modify: `backend/app/cli/main.py`
- Test: `backend/tests/test_chunking_service.py`

- [x] **Step 1: Write chunking tests**

Test that paragraph boundaries are preserved, chunk order is stable, and each chunk records `start_char`, `end_char`, `char_count`, and `checksum`.

- [x] **Step 2: Implement chunker**

Implement `ChunkingService.chunk_chapter(content, target_chars=1200, max_chars=1500)`:

```python
@dataclass(frozen=True)
class ChunkDraft:
    chunk_index: int
    text: str
    start_char: int
    end_char: int
    char_count: int
    token_count: int
    checksum: str
```

- [x] **Step 3: Persist chunks**

`ChunkRepository.replace_chunks_for_chapter()` should delete existing chunks for a chapter and insert the new chunk list in one transaction.

- [x] **Step 4: Add CLI command**

Add:

```powershell
python -m app.cli.main chunk-book --novel-id <uuid>
```

- [x] **Step 5: Verify**

Run:

```powershell
cd backend
python -m pytest tests/test_chunking_service.py -q
```

Expected: chunking tests pass.

**Acceptance Criteria:**
- Chunks are chapter-scoped.
- Chunks can be traced back to chapter text.
- No semantic chunking is introduced.

## Task 5: Embeddings And Retrieval Boundary

**Files:**
- Create: `backend/app/providers/embeddings.py`
- Create: `backend/app/services/embedding_service.py`
- Create: `backend/app/services/retrieval_service.py`
- Modify: `backend/app/repositories/chunks.py`
- Modify: `backend/app/cli/main.py`
- Test: `backend/tests/test_retrieval_service.py`

- [x] **Step 1: Write retrieval tests with fake embeddings**

Use a deterministic fake embedding provider that maps text to a 1536-dimensional vector so it matches `chapter_chunks.embedding`. Test that retrieval can filter by `novel_id`, optionally by chapter range, and returns chunk IDs plus text.

- [x] **Step 2: Define provider interface**

Create:

```python
class EmbeddingProvider(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...
```

- [x] **Step 3: Implement fake provider for tests**

Fake provider must not call external APIs and must return 1536-dimensional vectors.

- [x] **Step 4: Implement embedding persistence**

`EmbeddingService.embed_missing_chunks(novel_id)` should fetch chunks with null embeddings and write embeddings back.

- [x] **Step 5: Implement RetrievalService**

Expose:

```python
def search_chunks(
    self,
    novel_id: UUID,
    query: str,
    chapter_index: int | None = None,
    window: int = 1,
    limit: int = 8,
) -> list[RetrievedChunk]:
```

All pgvector SQL lives in this boundary.

- [x] **Step 6: Verify**

Run:

```powershell
cd backend
python -m pytest tests/test_retrieval_service.py -q
```

Expected: fake embedding retrieval tests pass.

**Acceptance Criteria:**
- Business services do not issue vector SQL directly.
- Retrieval supports chapter-window filtering.
- Qdrant is not introduced.

## Task 6: Character And Alias Candidate Workflow

**Files:**
- Create: `backend/app/services/character_service.py`
- Create: `backend/app/repositories/characters.py`
- Create: `backend/app/schemas/review_schema.py`
- Modify: `backend/app/cli/main.py`
- Test: `backend/tests/test_review_service.py`

- [x] **Step 1: Write candidate lifecycle tests**

Test creating a candidate character, accepting it, rejecting an alias, and merging an alias into a confirmed character.

- [x] **Step 2: Implement CharacterService**

Expose methods:

```python
create_character_candidate(...)
create_alias_candidate(...)
confirm_character(character_id, reviewer, note)
confirm_alias(alias_id, character_id, reviewer, note)
reject_candidate(target_type, target_id, reviewer, note)
```

- [x] **Step 3: Enforce confirmed character rule**

Alias confirmation must require the target character to be `confirmed`.

- [x] **Step 4: Add CLI review commands**

Add commands for listing candidates and confirming/rejecting by ID.

- [x] **Step 5: Verify**

Run:

```powershell
cd backend
python -m pytest tests/test_review_service.py -q
```

Expected: candidate lifecycle tests pass.

**Acceptance Criteria:**
- Characters and aliases use `candidate / confirmed / rejected`.
- Risky alias merges require explicit confirmation.
- Candidate characters do not become prompt-generation inputs.

## Task 7: Extraction Provider And Candidate Event/Change Storage

**Files:**
- Create: `backend/app/providers/llm.py`
- Create: `backend/app/services/extraction_service.py`
- Modify: `backend/app/repositories/states.py`
- Modify: `backend/app/cli/main.py`
- Test: `backend/tests/test_state_service.py`

- [x] **Step 1: Write extraction parsing tests**

Use a fake LLM provider returning structured JSON with one event and one state change. Test that source chunk IDs are required.

- [x] **Step 2: Define LLM provider protocol**

```python
class LlmProvider(Protocol):
    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        ...
```

- [x] **Step 3: Implement ExtractionService**

Input includes chapter summary, chunks, appearing characters, previous confirmed CharacterState, and recent confirmed CharacterEvents. Output creates `character_events` and `character_state_changes` with `status = candidate`.

- [x] **Step 4: Reject evidence-free output**

If an event or change has empty `source_chunk_ids`, store it as rejected with a review note or raise a validation error before persistence.

- [x] **Step 5: Add CLI command**

Add:

```powershell
python -m app.cli.main extract-chapter --chapter-id <uuid>
```

- [x] **Step 6: Verify**

Run:

```powershell
cd backend
python -m pytest tests/test_state_service.py -q
```

Expected: extraction candidate tests pass.

**Acceptance Criteria:**
- Extraction is chapter-level.
- Evidence is chunk-level.
- LLM output creates candidates only.

## Task 8: Initial CharacterState And State Synthesis

**Files:**
- Create: `backend/app/services/state_service.py`
- Create: `backend/app/repositories/states.py`
- Test: `backend/tests/test_state_service.py`

- [x] **Step 1: Write initial state tests**

Test that a character with no previous confirmed state can receive an initial candidate state with null `event_id` and null `state_change_id`, and that prompt generation cannot use it until confirmed.

- [x] **Step 2: Write state synthesis tests**

Given a previous confirmed state and a field-level state change, test that unchanged fields are copied and changed fields are applied.

- [x] **Step 3: Implement initial candidate creation**

Expose:

```python
create_initial_state_candidate(
    character_id: UUID,
    chapter_start: int,
    source_chunk_ids: list[UUID],
    fields: CharacterStateFields,
) -> CharacterState
```

- [x] **Step 4: Implement candidate synthesis**

Expose:

```python
synthesize_candidate_from_change(state_change_id: UUID) -> CharacterState
```

- [x] **Step 5: Verify**

Run:

```powershell
cd backend
python -m pytest tests/test_state_service.py -q
```

Expected: initial state and synthesis tests pass.

**Acceptance Criteria:**
- First appearances have a clear state creation path.
- LLM never directly rewrites an entire state without diff review.
- Candidate states cannot be used as formal prompt anchors.

## Task 9: Confirm State With Non-Overlapping Range Transaction

**Files:**
- Modify: `backend/app/services/state_service.py`
- Modify: `backend/app/repositories/states.py`
- Test: `backend/tests/test_state_service.py`

- [x] **Step 1: Write range lifecycle tests**

Cover:

```text
initial confirmed state: chapters 1-null
new candidate state at chapter 10
after confirmation:
  old state chapter_end = 9
  new state chapter_start = 10
  new state chapter_end = null
```

- [x] **Step 2: Write overlap rejection tests**

Test that confirming a new state with `chapter_start <= previous_state.chapter_start` fails and leaves existing states unchanged.

- [x] **Step 3: Implement transactional confirmation**

`confirm_state(candidate_state_id, reviewer, note)` must lock confirmed states for the character, close the previous state, mark the candidate confirmed, and check no overlap before commit.

- [x] **Step 4: Verify**

Run:

```powershell
cd backend
python -m pytest tests/test_state_service.py -q
```

Expected: range closure and overlap tests pass.

**Acceptance Criteria:**
- Confirmed CharacterState ranges do not overlap.
- Multiple matching confirmed states are treated as data integrity failure.
- State confirmation is atomic.

## Task 10: Evidence Chain Assembly

**Files:**
- Create: `backend/app/services/evidence_service.py`
- Modify: `backend/app/repositories/chunks.py`
- Modify: `backend/app/repositories/states.py`
- Test: `backend/tests/test_prompt_generation_service.py`

- [x] **Step 1: Write evidence tests**

Given state ID, event IDs, and chunk IDs, assert that EvidenceService returns a bundle containing state fields, event summaries, chunk text, chapter indexes, and source IDs.

- [x] **Step 2: Implement evidence bundle schema**

Use a serializable Pydantic model suitable for saving into `prompt_generations.evidence_snapshot_json`.

- [x] **Step 3: Implement EvidenceService**

Fetch and assemble state, event, and chunk records without changing their status.

- [x] **Step 4: Verify**

Run:

```powershell
cd backend
python -m pytest tests/test_prompt_generation_service.py -q
```

Expected: evidence assembly tests pass.

**Acceptance Criteria:**
- Prompt records can preserve evidence snapshots.
- Evidence includes concrete chunk IDs and source text.
- EvidenceService does not decide business priority; PromptGenerationService does.

## Task 11: Prompt Generation Service

**Files:**
- Create: `backend/app/services/prompt_generation_service.py`
- Create: `backend/app/repositories/prompts.py`
- Create: `backend/app/schemas/prompt_schema.py`
- Modify: `backend/app/cli/main.py`
- Test: `backend/tests/test_prompt_generation_service.py`

- [x] **Step 1: Write prompt generation tests**

Cover:

```text
confirmed state covering chapter X -> prompt generated
no confirmed state covering chapter X -> generation fails
candidate state only -> generation fails
explicit chunk clothing conflicts with durable state clothing -> warning saved
```

- [x] **Step 2: Implement state lookup**

Find state by:

```text
character_id = C
chapter_start <= X
(chapter_end >= X OR chapter_end IS NULL)
status = confirmed
```

If zero or multiple states match, return a typed error.

- [x] **Step 3: Implement context priority**

Generate prompt context in this order:

```text
confirmed CharacterState
current chapter and nearby chunks
recent confirmed CharacterEvents
```

- [x] **Step 4: Implement conflict warning**

Save explicit current-scene overrides into `warnings_json`.

- [x] **Step 5: Persist prompt generation**

Save `character_state_id`, `used_event_ids`, `used_chunk_ids`, `final_prompt`, `negative_prompt`, model parameters, warnings, and evidence snapshot.

- [x] **Step 6: Add CLI command**

Add:

```powershell
python -m app.cli.main generate-prompt --chapter-index <n> --character-id <uuid>
```

- [x] **Step 7: Verify**

Run:

```powershell
cd backend
python -m pytest tests/test_prompt_generation_service.py -q
```

Expected: prompt priority, failure, and warning tests pass.

**Acceptance Criteria:**
- Prompt generation uses confirmed CharacterState as anchor.
- Current chunks supplement scene details.
- Event evidence explains changes.
- Warnings are saved for state/chunk conflicts.

## Task 12: FastAPI Review And Prompt APIs

**Files:**
- Modify: `backend/app/api/main.py`
- Create: `backend/app/api/routes/review.py`
- Create: `backend/app/api/routes/states.py`
- Create: `backend/app/api/routes/prompts.py`
- Test: `backend/tests/test_review_service.py`
- Test: `backend/tests/test_prompt_generation_service.py`

- [x] **Step 1: Add API route tests**

Use FastAPI TestClient to verify routes call services and return JSON for candidate lists, review actions, state history, prompt generation, and prompt history.

- [x] **Step 2: Implement review routes**

Expose:

```text
GET /review/candidates
POST /review/{target_type}/{target_id}/accept
POST /review/{target_type}/{target_id}/reject
POST /review/aliases/{alias_id}/confirm
```

- [x] **Step 3: Implement state routes**

Expose:

```text
GET /characters/{character_id}/states
POST /characters/{character_id}/initial-state
```

- [x] **Step 4: Implement prompt routes**

Expose:

```text
POST /prompts/generate
GET /prompts/history
GET /prompts/{prompt_generation_id}
```

- [x] **Step 5: Verify**

Run:

```powershell
cd backend
python -m pytest -q
```

Expected: service and route tests pass.

**Acceptance Criteria:**
- API exposes only MVP review and prompt workflows.
- API uses services rather than direct repository orchestration.
- No user account or permission system is added.

## Task 13: Minimal React Admin Pages

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/api.ts`
- Create: `frontend/src/pages/CandidateReviewPage.tsx`
- Create: `frontend/src/pages/CharacterStatesPage.tsx`
- Create: `frontend/src/pages/PromptHistoryPage.tsx`

- [x] **Step 1: Create Vite React app structure**

Use React + TypeScript. Keep styling minimal and functional.

- [x] **Step 2: Implement API client**

`api.ts` should wrap the FastAPI endpoints from Task 12.

- [x] **Step 3: Implement CandidateReviewPage**

Show candidates with status, confidence, explanation, source chunks, and buttons for accept/reject. Alias confirmation can use an input for target `character_id`.

- [x] **Step 4: Implement CharacterStatesPage**

Show confirmed and candidate states for one character, including chapter range and field values.

- [x] **Step 5: Implement PromptHistoryPage**

Show prompt records with final prompt, warnings, used state ID, used event IDs, and used chunk IDs.

- [x] **Step 6: Verify**

Run:

```powershell
cd frontend
npm install
npm run build
```

Expected: production build succeeds.

**Acceptance Criteria:**
- Web UI supports review and inspection only.
- No file upload, realtime job progress, auth, or image gallery is added.
- Prompt evidence is visible enough to audit generation.

## Task 14: End-To-End MVP Fixture

**Files:**
- Create: `backend/tests/test_mvp_flow.py`
- Create: `backend/tests/fixtures/tiny_novel.md`
- Modify: `backend/app/services/import_service.py`
- Modify: `backend/app/services/chunking_service.py`
- Modify: `backend/app/services/embedding_service.py`
- Modify: `backend/app/services/character_service.py`
- Modify: `backend/app/services/state_service.py`
- Modify: `backend/app/services/prompt_generation_service.py`

- [x] **Step 1: Create tiny novel fixture**

Use a two or three chapter Markdown fixture where one character has an initial appearance and a later identity change.

- [x] **Step 2: Write end-to-end test**

The test should run:

```text
import fixture
chunk chapters
embed chunks with fake provider
create and confirm character
create initial CharacterState
create and confirm event/state change
confirm new CharacterState
generate chapter-specific prompt
assert prompt used correct state and evidence
```

- [x] **Step 3: Verify state-specific prompt difference**

Assert that chapter 1 and chapter 2 prompts for the same character use different state IDs and include different identity or visual keywords.

- [x] **Step 4: Verify**

Run:

```powershell
cd backend
python -m pytest tests/test_mvp_flow.py -q
```

Expected: end-to-end MVP fixture passes.

**Acceptance Criteria:**
- The smallest offline loop works without external LLM or embedding APIs.
- The same character can generate different prompts at different chapter stages.
- Evidence chain includes state, event, and chunk references.

## Task 15: Documentation And Operator Commands

**Files:**
- Create: `backend/README.md`
- Create: `frontend/README.md`
- Modify: `docs/superpowers/specs/2026-05-20-novel-character-visualization-design.md` only if implementation discoveries require spec corrections.

- [x] **Step 1: Document backend setup**

Include database setup, migrations, test command, and CLI examples.

- [x] **Step 2: Document MVP flow commands**

List commands in order:

```powershell
python -m app.cli.main import-book --path samples/book.md --title "Sample"
python -m app.cli.main chunk-book --novel-id <uuid>
python -m app.cli.main embed-book --novel-id <uuid>
python -m app.cli.main extract-chapter --chapter-id <uuid>
python -m app.cli.main generate-prompt --chapter-index 1 --character-id <uuid>
```

- [x] **Step 3: Document frontend setup**

Include `npm install`, `npm run dev`, and the FastAPI base URL setting.

- [x] **Step 4: Verify all checks**

Run:

```powershell
cd backend
python -m pytest -q
```

Run:

```powershell
cd frontend
npm run build
```

Expected: backend tests pass and frontend build succeeds.

**Acceptance Criteria:**
- A new engineer can run the MVP flow from README commands.
- Documentation keeps Qdrant, Neo4j, Celery, crawlers, and group prompts out of phase one setup.

## Testing Strategy

Core tests must cover:

- Chapter import and deterministic chapter indexes.
- Paragraph-preserving chunk boundaries and source offsets.
- Retrieval boundary using fake embeddings.
- Candidate lifecycle for characters and aliases.
- Evidence-required extraction output validation.
- Initial CharacterState creation when no previous state exists.
- CharacterState synthesis from field-level changes.
- Confirmed state range closure.
- Rejection of overlapping confirmed state ranges.
- Prompt generation failure when no confirmed state covers chapter X.
- Prompt generation refusal to use candidate states.
- Prompt conflict warnings.
- Evidence snapshot persistence.
- End-to-end fixture proving different prompts for the same character at different story stages.

Use fake embedding and fake LLM providers in tests. External provider integration can be added after the MVP loop is stable.

## Self-Review

### Spec Coverage

This plan covers import, chapter storage, chunking, embeddings, retrieval, character and alias review, chapter-level extraction, field-level CharacterStateChange, initial CharacterState creation, state confirmation with non-overlap checks, prompt generation, evidence snapshots, minimal Web review pages, and the end-to-end MVP fixture.

### Scope Check

The plan does not implement crawlers, Qdrant, Neo4j, Celery, complete Web product features, group prompts, or mandatory image generation APIs.

### Type Consistency

MVP `PromptType` is limited to `character` and `scene`. CharacterState lifecycle uses `candidate / confirmed / rejected` consistently. Formal generation requires confirmed character, event, state change, and state records.

### Placeholder Scan

The plan avoids open-ended implementation placeholders. Each task includes target files, verification commands, and acceptance criteria.

# Novel Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-stop `Novel Workspace` page and the minimum thin backend APIs needed to operate the completed phase 1 MVP from one browser surface.

**Architecture:** Keep the Postgres-centered modular monolith. New FastAPI routes remain thin and call existing repositories/services; the React page remains a thin client and does not duplicate state lifecycle, extraction, evidence, or prompt rules. PostgreSQL + pgvector remains the only source of truth.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL + pgvector, pytest, ruff, React + Vite + TypeScript.

---

## Scope Guardrails

This plan does not add:

- upload or import API;
- full-book extraction from the browser;
- Celery, Redis, task queue, progress tracking, cancellation, or retry;
- Qdrant or Neo4j;
- real FastGPT integration or FastGPT configuration UI;
- image generation API;
- group prompt;
- auth, permissions, collaboration, or a complete Web product.

The browser starts from an existing `novel_id`. Local import remains a CLI/operator workflow.

## Target File Map

Backend:

- Modify `backend/app/repositories/novels.py`: add novel lookup and lightweight chapter summary queries.
- Modify `backend/app/repositories/chunks.py`: add chunk preview helpers and counts for embedding status.
- Modify `backend/app/repositories/characters.py`: add character list by status and downstream candidate checks.
- Modify `backend/app/repositories/states.py`: add novel-scoped downstream event/state/change counts if not already available.
- Modify `backend/app/repositories/prompts.py`: add prompt count by novel if not already available.
- Create `backend/app/api/routes/novels.py`: expose novel metadata, chapters, processing status, character listing, chunk, and embed endpoints.
- Create `backend/app/api/routes/chapters.py`: expose chapter chunk previews and single-chapter extraction endpoint.
- Modify `backend/app/api/routes/states.py`: add `POST /states/{state_id}/confirm`.
- Modify `backend/app/api/main.py`: include new routers.
- Modify `backend/tests/test_api_routes.py`: cover new endpoints and dangerous chunk boundary.

Frontend:

- Modify `frontend/src/api.ts`: add new types and client functions.
- Create `frontend/src/pages/NovelWorkspacePage.tsx`: one-stop workspace page.
- Modify `frontend/src/main.tsx`: add default `Workspace` tab and keep existing tabs.
- Modify `frontend/src/styles.css`: add compact workspace layout styles using existing visual language.

Docs:

- Modify `backend/README.md`: add new API summary and note that Workspace chunking is blocked after downstream knowledge exists.
- Modify `frontend/README.md`: add `Workspace` page description.

## Checkpoint 1: Backend Query APIs

**Goal:** Add read-only APIs for novel metadata, chapter summaries, chunk previews, processing status, and character listing.

**Files:**

- Modify: `backend/app/repositories/novels.py`
- Modify: `backend/app/repositories/chunks.py`
- Modify: `backend/app/repositories/characters.py`
- Modify: `backend/app/repositories/states.py`
- Modify: `backend/app/repositories/prompts.py`
- Create: `backend/app/api/routes/novels.py`
- Create: `backend/app/api/routes/chapters.py`
- Modify: `backend/app/api/main.py`
- Test: `backend/tests/test_api_routes.py`

**New APIs:**

- `GET /novels/{novel_id}`
- `GET /novels/{novel_id}/chapters`
- `GET /chapters/{chapter_id}/chunks`
- `GET /novels/{novel_id}/processing-status`
- `GET /novels/{novel_id}/characters?status=confirmed`

**Frontend components:** none in this checkpoint.

- [x] **Step 1: Add route tests for novel metadata and chapter summaries**

Add tests in `backend/tests/test_api_routes.py` that create a novel with chapters and chunks, then assert:

```python
def test_get_novel_metadata_excludes_chapter_content(client, pg_session):
    response = client.get(f"/novels/{novel.id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(novel.id)
    assert payload["title"] == novel.title
    assert "content" not in payload


def test_list_chapters_returns_lightweight_counts(client, pg_session):
    response = client.get(f"/novels/{novel.id}/chapters")
    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["chapter_index"] == 1
    assert payload[0]["chunk_count"] == 1
    assert payload[0]["embedded_count"] in {0, 1}
    assert "content" not in payload[0]
```

Run:

```powershell
cd backend
.\.venv\Scripts\python -m pytest tests/test_api_routes.py -q
```

Expected: new tests fail because routes do not exist.

- [x] **Step 2: Add repository query helpers**

Add repository methods with these signatures:

```python
class NovelRepository(BaseRepository[Novel]):
    def get_novel(self, novel_id: uuid.UUID) -> Novel | None: ...
    def list_chapter_summaries(self, novel_id: uuid.UUID) -> list[ChapterSummaryRow]: ...

class ChunkRepository(BaseRepository[ChapterChunk]):
    def count_chunks_for_novel(self, novel_id: uuid.UUID) -> int: ...
    def count_embedded_chunks_for_novel(self, novel_id: uuid.UUID) -> int: ...
    def list_chunk_previews_for_chapter(self, chapter_id: uuid.UUID) -> list[ChapterChunk]: ...

class CharacterRepository(BaseRepository[Character]):
    def list_characters(self, novel_id: uuid.UUID, status: str | None) -> list[Character]: ...
    def count_characters(self, novel_id: uuid.UUID, status: str) -> int: ...
    def count_aliases(self, novel_id: uuid.UUID, status: str) -> int: ...

class StateRepository(BaseRepository[CharacterState]):
    def count_events(self, novel_id: uuid.UUID, status: str | None = None) -> int: ...
    def count_state_changes(self, novel_id: uuid.UUID, status: str | None = None) -> int: ...
    def count_states(self, novel_id: uuid.UUID, status: str | None = None) -> int: ...

class PromptRepository(BaseRepository[PromptGeneration]):
    def count_prompt_generations(self, novel_id: uuid.UUID) -> int: ...
```

Use SQLAlchemy `select()` and `func.count()`. Keep SQL in repositories, not routes.

- [x] **Step 3: Add read-only routes**

Create `backend/app/api/routes/novels.py` and `backend/app/api/routes/chapters.py`.

Route behavior:

- `GET /novels/{novel_id}` returns metadata only.
- `GET /novels/{novel_id}/chapters` returns `id`, `title`, `chapter_index`, `word_count`, `chunk_count`, `embedded_count`.
- `GET /chapters/{chapter_id}/chunks` returns chunk metadata plus `text_preview = chunk.text[:240]`.
- `GET /novels/{novel_id}/processing-status` returns summary counts from repositories.
- `GET /novels/{novel_id}/characters?status=...` accepts `candidate`, `confirmed`, `rejected`, and `all`; unsupported values raise `ValueError`.

- [x] **Step 4: Register routers**

Modify `backend/app/api/main.py`:

```python
from app.api.routes import chapters, novels, prompts, review, states

app.include_router(novels.router)
app.include_router(chapters.router)
```

Keep existing CORS and `ValueError -> 400` handler.

- [x] **Step 5: Verify checkpoint**

Run:

```powershell
cd backend
.\.venv\Scripts\python -m pytest tests/test_api_routes.py -q
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m ruff check app tests alembic
```

Expected:

```text
all tests passed
ruff passed
```

**Explicitly not in this checkpoint:** processing mutations, frontend changes, upload/import API, full-book extraction, queues, FastGPT, Qdrant, Neo4j, image generation, group prompt.

## Checkpoint 2: Backend Processing APIs

**Goal:** Add thin synchronous APIs for chunking, embedding, single-chapter extraction, and state confirmation, with the chunk rebuild safety boundary enforced.

**Files:**

- Modify: `backend/app/repositories/characters.py`
- Modify: `backend/app/repositories/states.py`
- Modify: `backend/app/repositories/prompts.py`
- Modify: `backend/app/api/routes/novels.py`
- Modify: `backend/app/api/routes/chapters.py`
- Modify: `backend/app/api/routes/states.py`
- Test: `backend/tests/test_api_routes.py`

**New/modified APIs:**

- `POST /novels/{novel_id}/chunk`
- `POST /novels/{novel_id}/embed`
- `POST /chapters/{chapter_id}/extract`
- `POST /states/{state_id}/confirm`

**Frontend components:** none in this checkpoint.

- [x] **Step 1: Write tests for chunk rebuild safety**

Add route tests covering both allowed and blocked cases:

```python
def test_chunk_novel_succeeds_without_downstream_knowledge(client, pg_session):
    response = client.post(f"/novels/{novel.id}/chunk", json={"target_chars": 1200, "max_chars": 1500})
    assert response.status_code == 200
    payload = response.json()
    assert payload["novel_id"] == str(novel.id)
    assert payload["chapter_count"] >= 1
    assert payload["chunk_count"] >= 1


def test_chunk_novel_rejects_when_character_candidate_has_chunk_evidence(client, pg_session):
    response = client.post(f"/novels/{novel.id}/chunk", json={"target_chars": 1200, "max_chars": 1500})
    assert response.status_code == 400
    assert "chunk-based knowledge" in response.json()["detail"]


def test_chunk_novel_rejects_when_event_state_or_prompt_exists(client, pg_session):
    response = client.post(f"/novels/{novel.id}/chunk", json={"target_chars": 1200, "max_chars": 1500})
    assert response.status_code == 400
    assert "Workspace chunk rebuild is blocked" in response.json()["detail"]
```

Create separate fixtures or setup blocks for character candidate evidence, `CharacterEvent`, `CharacterStateChange`, `CharacterState`, and `PromptGeneration` so each downstream category is covered.

Run:

```powershell
cd backend
.\.venv\Scripts\python -m pytest tests/test_api_routes.py -q
```

Expected: new tests fail because safety check and routes are not complete.

- [x] **Step 2: Add downstream knowledge check helpers**

Add repository-level checks that can answer:

```python
CharacterRepository.has_chunk_evidence_candidates(novel_id) -> bool
StateRepository.has_events_or_states_for_novel(novel_id) -> bool
PromptRepository.has_prompt_generations(novel_id) -> bool
```

`has_chunk_evidence_candidates` returns true when a `Character` or `CharacterAlias` row for the novel has a non-empty `source_chunk_ids` value. It should not block on characters or aliases with empty evidence.

- [x] **Step 3: Implement `POST /novels/{novel_id}/chunk`**

In `backend/app/api/routes/novels.py`, implement:

```text
POST /novels/{novel_id}/chunk
```

Behavior:

- Look up chapters for the novel.
- Before replacing chunks, call downstream knowledge checks.
- If downstream knowledge exists, raise:

```python
ValueError(
    "This novel already has chunk-based knowledge or prompt records. "
    "Workspace chunk rebuild is blocked; use a CLI/database rebuild flow "
    "or a future dedicated rebuild workflow."
)
```

- If allowed, call `ChunkingService.chunk_chapter()` and `ChunkRepository.replace_chunks_for_chapter()` for each chapter.
- Commit in the route after service/repository calls complete.
- Return `novel_id`, `chapter_count`, `chunk_count`, `replaced_existing_chunks`.

Do not add evidence migration, cascading cleanup, rebuild workflow, queue, progress, cancel, or retry.

- [x] **Step 4: Implement `POST /novels/{novel_id}/embed`**

Route behavior:

- Instantiate `get_settings()`.
- Use `get_embedding_provider(settings.embedding_provider)`.
- Call `EmbeddingService(ChunkRepository(db), provider).embed_missing_chunks(novel_id, batch_size=request.batch_size)`.
- Return `novel_id`, `embedded_count`, `remaining_missing_embedding_count`, and `provider`.
- Commit after embeddings are updated.

- [x] **Step 5: Implement `POST /chapters/{chapter_id}/extract`**

Route behavior:

- Instantiate `get_settings()`.
- Use `get_llm_provider(settings.llm_provider)`.
- Call `ExtractionService.extract_chapter_candidates(chapter_id)`.
- Return `chapter_id`, `chapter_index`, `event_candidate_count`, and `state_change_candidate_count`.
- Commit after candidate rows are created.
- Keep extraction single-chapter only.

- [x] **Step 6: Implement `POST /states/{state_id}/confirm`**

Modify `backend/app/api/routes/states.py`.

Route behavior:

- Add router for `POST /states/{state_id}/confirm` without changing existing `/characters` routes.
- Request body has `reviewer: str = "api"` and `note: str | None = None`.
- Call `StateService(StateRepository(db)).confirm_state(state_id, reviewer, note)`.
- Commit and return the same state response shape as existing state routes.

- [x] **Step 7: Verify checkpoint**

Run:

```powershell
cd backend
.\.venv\Scripts\python -m pytest tests/test_api_routes.py -q
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m ruff check app tests alembic
```

Expected:

```text
all tests passed
ruff passed
```

**Explicitly not in this checkpoint:** frontend changes, upload/import API, full-book extraction, rebuild workflow, evidence migration, task queue, FastGPT, Qdrant, Neo4j, image generation, group prompt.

## Checkpoint 3: Frontend API Client

**Goal:** Add typed API helpers for all Novel Workspace backend endpoints.

**Files:**

- Modify: `frontend/src/api.ts`

**APIs used by frontend:**

- Existing review, state, and prompt APIs.
- New novel, chapter, chunk, processing, character, chunk, embed, extract, and confirm-state APIs.

**Frontend components:** none in this checkpoint.

- [x] **Step 1: Add response types**

Add exported TypeScript types:

```ts
export type NovelSummary = {
  id: string;
  title: string;
  author: string | null;
  source_type: string;
  language: string;
  imported_at: string | null;
  created_at: string;
};

export type ChapterSummary = {
  id: string;
  title: string;
  chapter_index: number;
  word_count: number;
  chunk_count: number;
  embedded_count: number;
};

export type ChunkPreview = {
  id: string;
  novel_id: string;
  chapter_id: string;
  chapter_index: number;
  chunk_index: number;
  char_count: number;
  token_count: number;
  has_embedding: boolean;
  text_preview: string;
};

export type ProcessingStatus = {
  novel_id: string;
  chapter_count: number;
  chunk_count: number;
  embedded_count: number;
  missing_embedding_count: number;
  candidate_character_count: number;
  confirmed_character_count: number;
  candidate_alias_count: number;
  candidate_event_count: number;
  candidate_state_change_count: number;
  candidate_state_count: number;
  confirmed_state_count: number;
  prompt_generation_count: number;
};

export type CharacterSummary = {
  id: string;
  novel_id: string;
  canonical_name: string;
  status: string;
  description: string | null;
  confidence: number | null;
};
```

- [x] **Step 2: Add client methods**

Add functions:

```ts
export function getNovel(novelId: string): Promise<NovelSummary>;
export function listChapters(novelId: string): Promise<ChapterSummary[]>;
export function listChapterChunks(chapterId: string): Promise<ChunkPreview[]>;
export function getProcessingStatus(novelId: string): Promise<ProcessingStatus>;
export function listCharacters(novelId: string, status: "candidate" | "confirmed" | "rejected" | "all"): Promise<CharacterSummary[]>;
export function chunkNovel(novelId: string, payload?: { target_chars?: number; max_chars?: number }): Promise<{ novel_id: string; chapter_count: number; chunk_count: number; replaced_existing_chunks: boolean }>;
export function embedNovel(novelId: string, payload?: { batch_size?: number }): Promise<{ novel_id: string; embedded_count: number; remaining_missing_embedding_count: number; provider: string }>;
export function extractChapter(chapterId: string): Promise<{ chapter_id: string; chapter_index: number; event_candidate_count: number; state_change_candidate_count: number }>;
export function confirmState(stateId: string, reviewer: string, note?: string): Promise<CharacterState>;
```

Keep `request<T>()` unchanged unless tests reveal an error.

- [x] **Step 3: Verify checkpoint**

Run:

```powershell
cd frontend
npm run build
```

Expected:

```text
build passed
```

**Explicitly not in this checkpoint:** new UI page, backend changes, provider config UI, upload/import, task queue, full product navigation.

## Checkpoint 4: NovelWorkspacePage Basic Loading

**Goal:** Add the default `Workspace` tab and load novel metadata, processing status, chapters, chunks, confirmed characters, candidates, and prompt history.

**Files:**

- Create: `frontend/src/pages/NovelWorkspacePage.tsx`
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/styles.css`

**APIs used:**

- `GET /novels/{novel_id}`
- `GET /novels/{novel_id}/processing-status`
- `GET /novels/{novel_id}/chapters`
- `GET /chapters/{chapter_id}/chunks`
- `GET /review/candidates?novel_id=<novel_id>`
- `GET /novels/{novel_id}/characters?status=confirmed`
- `GET /prompts/history?novel_id=<novel_id>`

**New frontend component:**

- `NovelWorkspacePage`

- [x] **Step 1: Create workspace component state**

Create `NovelWorkspacePage.tsx` with state for:

```ts
const [novelId, setNovelId] = useState("");
const [novel, setNovel] = useState<NovelSummary | null>(null);
const [status, setStatus] = useState<ProcessingStatus | null>(null);
const [chapters, setChapters] = useState<ChapterSummary[]>([]);
const [selectedChapter, setSelectedChapter] = useState<ChapterSummary | null>(null);
const [chunks, setChunks] = useState<ChunkPreview[]>([]);
const [candidates, setCandidates] = useState<Candidate[]>([]);
const [characters, setCharacters] = useState<CharacterSummary[]>([]);
const [selectedCharacterId, setSelectedCharacterId] = useState("");
const [prompts, setPrompts] = useState<PromptGeneration[]>([]);
const [message, setMessage] = useState("");
const [loading, setLoading] = useState(false);
```

- [x] **Step 2: Implement `loadWorkspace()`**

`loadWorkspace()` should:

- trim `novelId`;
- call metadata, status, chapters, candidates, confirmed characters, and prompt history;
- select the first chapter when no selected chapter exists;
- show errors in `message`.

Use `Promise.all()` for independent reads.

- [x] **Step 3: Implement chapter selection and chunk loading**

When a chapter row is selected:

- set `selectedChapter`;
- call `listChapterChunks(chapter.id)`;
- display chunk previews and `has_embedding`.

- [x] **Step 4: Add read-only layout sections**

Render these sections:

- Novel Overview;
- Chapter And Processing;
- Candidate Review summary;
- Character State summary placeholder;
- Prompt Lab summary placeholder.

At this checkpoint, Candidate Review, State, and Prompt sections can show loaded counts and selected IDs but no mutations.

- [x] **Step 5: Make Workspace the default tab**

Modify `frontend/src/main.tsx`:

```ts
import { NovelWorkspacePage } from "./pages/NovelWorkspacePage";

type Tab = "workspace" | "review" | "states" | "prompts";
const [tab, setTab] = useState<Tab>("workspace");
```

Add the `Workspace` tab before existing tabs and render `NovelWorkspacePage` when selected. Keep `Review`, `States`, and `Prompts`.

- [x] **Step 6: Verify checkpoint**

Run:

```powershell
cd frontend
npm run build
```

Expected:

```text
build passed
```

**Explicitly not in this checkpoint:** processing buttons, candidate mutation buttons, state confirmation, prompt generation, upload/import, full Web product features.

## Checkpoint 5: Workspace Operations Integration

**Goal:** Wire the one-stop page to processing, review, state, and prompt operations while keeping business rules in the backend.

**Files:**

- Modify: `frontend/src/pages/NovelWorkspacePage.tsx`
- Modify: `frontend/src/styles.css`

**APIs used:**

- `POST /novels/{novel_id}/chunk`
- `POST /novels/{novel_id}/embed`
- `POST /chapters/{chapter_id}/extract`
- `POST /review/{target_type}/{target_id}/accept`
- `POST /review/{target_type}/{target_id}/reject`
- `POST /review/aliases/{alias_id}/confirm`
- `GET /characters/{character_id}/states`
- `POST /characters/{character_id}/initial-state`
- `POST /states/{state_id}/confirm`
- `POST /prompts/generate`
- `GET /prompts/{prompt_generation_id}`

**Frontend component:**

- Modify `NovelWorkspacePage`.

- [x] **Step 1: Add processing actions**

Add buttons:

- `Chunk Novel`;
- `Embed Missing Chunks`;
- `Extract Selected Chapter`.

Each action:

- disables while loading;
- calls the API client;
- displays success or error in `message`;
- refreshes status and chapters after success;
- refreshes candidates after extraction.

For chunk errors, display the backend 400 message about existing chunk-based knowledge without client-side reinterpretation.

- [x] **Step 2: Add compact candidate review actions**

In the Candidate Review section:

- show candidate type, label, confidence, and status;
- allow selecting one candidate;
- accept only character candidates through `acceptCandidate`;
- reject character or alias candidates through `rejectCandidate`;
- confirm alias through `confirmAlias(aliasId, targetCharacterId, reviewer, note)`;
- refresh candidates and confirmed characters after mutation.

- [x] **Step 3: Add state timeline and state confirmation**

When `selectedCharacterId` changes:

- call `listStates(selectedCharacterId)`;
- render chapter range, status, identity, appearance, visual keywords, and source chunk IDs;
- allow selecting a candidate state;
- add `Confirm Selected State` button calling `confirmState`.

State confirmation errors are shown inline. The frontend does not close ranges or validate overlap.

- [x] **Step 4: Add initial state candidate form**

Add a compact initial state form with:

- `chapter_start`;
- `source_chunk_ids`;
- `appearance`;
- `personality`;
- `identity`;
- `motivation`;
- `relationship_summary`;
- `visual_keywords`;
- `negative_prompt`;
- `confidence`.

Submit calls existing `createInitialState(selectedCharacterId, payload)`.

The form uses the loaded `novel_id` and selected character. It requires at least one source chunk ID.

- [x] **Step 5: Add Prompt Lab**

Add prompt inputs:

- selected chapter index from the chapter table;
- selected confirmed character from character list;
- optional user request.

On submit:

- call `generatePrompt`;
- display `final_prompt`, `negative_prompt`, `warnings`, and `evidence_snapshot`;
- refresh prompt history.

Prompt errors such as missing confirmed CharacterState are shown inline.

- [x] **Step 6: Add prompt history/detail inspection**

Render prompt history rows with:

- chapter index;
- prompt type;
- character state ID;
- warning count.

On row click:

- call `getPromptDetail`;
- display full prompt detail in Prompt Lab.

- [x] **Step 7: Verify checkpoint**

Run:

```powershell
cd frontend
npm run build
```

Expected:

```text
build passed
```

Then run backend checks to verify no accidental API regression:

```powershell
cd backend
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m ruff check app tests alembic
```

Expected:

```text
all tests passed
ruff passed
```

**Explicitly not in this checkpoint:** file upload/import, full-book extraction, queue/progress UI, FastGPT UI, image gallery, group prompt UI, auth, complete product dashboard.

## Checkpoint 6: Final Verification And Docs

**Goal:** Update operator docs and verify the final one-stop workspace scope.

**Files:**

- Modify: `backend/README.md`
- Modify: `frontend/README.md`
- Optional modify: `docs/superpowers/specs/2026-05-20-one-stop-workspace-design.md` only if implementation reveals a mismatch that must be documented before acceptance.

**APIs:** no new APIs in this checkpoint.

**Frontend components:** no new components in this checkpoint.

- [x] **Step 1: Update backend README**

Add a short `Novel Workspace APIs` section listing:

```text
GET  /novels/{novel_id}
GET  /novels/{novel_id}/chapters
GET  /chapters/{chapter_id}/chunks
GET  /novels/{novel_id}/processing-status
GET  /novels/{novel_id}/characters?status=confirmed
POST /novels/{novel_id}/chunk
POST /novels/{novel_id}/embed
POST /chapters/{chapter_id}/extract
POST /states/{state_id}/confirm
```

Document the `chunk novel` safety rule:

```text
Workspace chunking is blocked after chunk-based knowledge or prompt records exist for the novel, because replacing chunks would invalidate evidence IDs.
```

- [x] **Step 2: Update frontend README**

Add `Workspace` to the pages list:

```text
Workspace: one-stop page that starts from novel_id, loads chapter/chunk/status data, runs small synchronous processing actions, reviews candidates, inspects states, confirms state candidates, and generates/audits prompts.
```

State that existing `Review`, `States`, and `Prompts` pages remain available.

- [x] **Step 3: Run final verification**

Run:

```powershell
cd backend
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m ruff check app tests alembic
```

Expected:

```text
all tests passed
ruff passed
```

Run:

```powershell
cd frontend
npm run build
```

Expected:

```text
build passed
```

- [x] **Step 4: Boundary self-review**

Inspect changed files and confirm:

- no upload/import API was added;
- no full-book extraction route or button was added;
- no Celery, Redis, task queue, progress tracking, cancellation, or retry was added;
- no Qdrant or Neo4j dependency was added;
- no FastGPT implementation or configuration UI was added;
- no image generation API or gallery was added;
- no group prompt support was added;
- no auth, permissions, or collaboration was added;
- `chunk novel` blocks when downstream knowledge exists;
- new APIs are thin routes over existing services/repositories;
- frontend does not duplicate state lifecycle or prompt evidence rules.

**Explicitly not in this checkpoint:** implementation of any new product capability beyond documentation and verification.

## Overall Testing Strategy

Backend:

- Use existing real Postgres/pgvector `pg_session` fixture for route tests.
- Keep SQLite out of repository/service integration paths.
- Cover all new route behavior in `backend/tests/test_api_routes.py`.
- Specifically cover the dangerous chunk rebuild boundary before wiring the frontend button.

Frontend:

- Use TypeScript build as the MVP verification gate.
- Keep UI logic simple and typed through `frontend/src/api.ts`.
- Do not add a browser E2E suite in this round unless a later review requests it.

Final commands:

```powershell
cd backend
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m ruff check app tests alembic
```

```powershell
cd frontend
npm run build
```

## Plan Self-Review

### Spec Coverage

This plan covers the approved spec: `Novel Workspace` default tab, lightweight novel/chapter/chunk/status APIs, confirmed character listing, synchronous chunk/embed/single-chapter extraction APIs, state confirmation API, frontend workspace loading, processing actions, candidate review, state timeline, prompt generation/detail, docs, and final verification.

### Placeholder Scan

The plan contains no open placeholder markers. Each checkpoint has concrete files, APIs, frontend components, commands, and expected outcomes.

### Checkpoint Independence

Each checkpoint can be verified independently:

- Checkpoint 1: backend read APIs and route tests.
- Checkpoint 2: backend processing APIs and dangerous chunk boundary tests.
- Checkpoint 3: frontend API client build.
- Checkpoint 4: workspace read-only loading build.
- Checkpoint 5: workspace operations build plus backend regression checks.
- Checkpoint 6: docs and final verification.

### Dangerous Boundary Coverage

Checkpoint 2 requires tests proving `chunk novel` returns 400 when downstream knowledge exists and succeeds only before downstream knowledge exists.

### Thin API And Thin Frontend Check

The backend routes call existing repositories/services. The frontend calls typed API helpers and displays returned data; it does not implement state range closure, overlap checks, extraction validation, evidence filtering, or prompt-generation rules.

### Scope Check

The plan does not add upload/import API, full-book extraction, Celery/Redis, Qdrant, Neo4j, real FastGPT integration, image generation, group prompt, auth, permissions, collaboration, or a complete Web product.

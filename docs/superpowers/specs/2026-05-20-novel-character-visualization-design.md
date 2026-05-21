# Novel Character Visualization And Knowledge Base Design

Date: 2026-05-20

## Goal

Build a first-stage MVP for a novel character visualization and knowledge base system.

The MVP validates one core loop:

```text
Novel import
-> chapter splitting
-> chunk storage and embedding retrieval
-> character and alias candidates
-> chapter-level event and state-change extraction
-> human review
-> chapter-specific character image prompt generation
-> saved evidence chain
```

The most important product behavior is that the same character can produce different prompts at different story stages, and those differences must come from confirmed character state, source chunks, and confirmed events rather than model invention.

## Non-Goals For MVP

The first phase does not include:

- Website crawling or anti-scraping logic.
- A complete web product.
- User accounts, permissions, or collaboration.
- Celery and Redis as required infrastructure.
- Qdrant.
- Neo4j.
- Complex story arc modeling.
- Field-level state version tables.
- Mandatory image generation API integration.
- A full plugin system for storage backends.

Future integrations should be possible, but they must not complicate the MVP path.

## Architecture

Use a Postgres-centered modular monolith.

```text
React admin page
  -> FastAPI API
  -> service layer
  -> repository layer
  -> PostgreSQL + pgvector

CLI
  -> same service layer
  -> same repository layer
  -> PostgreSQL + pgvector
```

PostgreSQL with pgvector is the only source of truth in phase one.

The CLI and the web admin page must call the same services. CLI commands should not bypass business services to mutate tables directly. The web page should also avoid duplicating business rules in frontend code.

Suggested backend modules:

```text
app/
  api/                 # FastAPI routes
  cli/                 # offline commands
  core/                # config, db, logging, provider registry
  importers/           # TXT/EPUB/Markdown -> BookManifest + Chapter[]
  chunking/            # paragraph-preserving chunker
  embeddings/          # embedding providers and persistence
  retrieval/           # pgvector retrieval boundary
  characters/          # characters and aliases
  extraction/          # chapter-level LLM extraction
  review/              # accept/edit/merge/reject workflows
  states/              # state synthesis and lifecycle rules
  prompts/             # image prompt generation
  evidence/            # evidence-chain assembly
  repositories/        # SQLAlchemy repositories
```

## Data Model

All candidate and formal entities use one table per concept, with `status` distinguishing lifecycle:

```text
candidate / confirmed / rejected
```

Business queries that feed prompt generation must filter `status = confirmed`.

Candidate records can be shown in review screens and edited, merged, accepted, or rejected. They must not be used as formal knowledge for generation unless explicitly confirmed.

### novels

Stores one imported book.

```text
id
title
author
source_type              # txt / epub / markdown / manifest
language
source_path
metadata_json
imported_at
created_at
```

### chapters

Stores normalized chapter text.

```text
id
novel_id
chapter_index
title
content
summary
source_path
word_count
checksum
created_at
```

`chapter_index` is the story-order key used by state ranges and generation queries.

### chapter_chunks

Stores retrievable evidence chunks.

```text
id
novel_id
chapter_id
chapter_index
chunk_index
text
start_char
end_char
char_count
token_count
checksum
embedding vector
metadata_json
created_at
```

Chunks should be created by paragraph aggregation inside each chapter. The target size is roughly 800-1500 Chinese characters, adjusted by model token limits. Small overlap is allowed, but paragraph integrity should be preserved.

Chunks must be traceable back to chapter text through `chapter_id`, `start_char`, and `end_char`.

### characters

Stores candidate and confirmed character entities.

```text
id
novel_id
canonical_name
description
status
source_chunk_ids
confidence
reviewed_at
reviewed_by
review_note
created_at
updated_at
```

CharacterState and CharacterEvent records used in generation must attach to confirmed characters.

### character_aliases

Stores names, titles, nicknames, disguises, and other references to characters.

```text
id
novel_id
character_id             # nullable while candidate
alias_text
alias_type               # name / title / nickname / disguise / unknown
status
source_chunk_ids
context_excerpt
confidence
merge_suggestion_json
reviewed_at
reviewed_by
review_note
created_at
```

Alias merging is review-driven. The system may suggest that two aliases refer to the same character, but risky merges require human confirmation.

### character_events

Stores important events that may affect character state.

```text
id
novel_id
character_id
chapter_id
chapter_index
event_summary
event_type               # appearance / identity / relationship / motivation / other
is_long_term_change
affected_fields          # JSON array
source_chunk_ids
confidence
explanation
status
supersedes_id
merged_into_id
reviewed_at
reviewed_by
review_note
created_at
```

Only confirmed events can be used as formal state-change causes or prompt evidence. Candidate events can appear in review workflows.

### character_state_changes

Stores field-level change suggestions extracted by the LLM.

```text
id
novel_id
character_id
event_id
chapter_id
chapter_index
changed_fields_json
source_chunk_ids
confidence
explanation
status
reviewed_at
reviewed_by
review_note
created_at
```

`changed_fields_json` should contain entries like:

```json
[
  {
    "field": "identity",
    "before": "outer disciple",
    "after": "inner disciple",
    "confidence": 0.87,
    "source_chunk_ids": ["..."]
  }
]
```

The MVP stores full CharacterState snapshots, not field-level state timelines. Field-level changes exist to make review and state synthesis auditable.

### character_states

Stores full state snapshots for a character across a chapter range.

```text
id
novel_id
character_id
chapter_start
chapter_end              # null means active until replaced
appearance
personality
identity
motivation
relationship_summary
visual_keywords
negative_prompt
source_chapters
source_chunk_ids
event_id
state_change_id
confidence
status
supersedes_id
merged_into_id
reviewed_at
reviewed_by
review_note
created_at
updated_at
```

CharacterState represents a relatively stable character snapshot during a story range. It should not be created for temporary emotions or one-scene behavior unless that event changes long-term appearance, identity, personality, motivation, or relationships.

### prompt_generations

Stores generated prompt records and their evidence chain.

```text
id
novel_id
chapter_id
chapter_index
character_id             # nullable for pure scene prompt
character_state_id
prompt_type              # character / scene; group is future scope
user_request
final_prompt
negative_prompt
model_provider
model_name
model_params_json
used_event_ids
used_chunk_ids
warnings_json
evidence_snapshot_json
created_at
```

`evidence_snapshot_json` should preserve the state, event, and chunk evidence used at generation time so the record remains auditable even if source records are later edited.

MVP prompt generation supports single-character prompts and simple scene prompts. Group prompts are future scope because they require a multi-character association table such as `prompt_generation_characters`.

### generated_images

Optional in MVP. Stores generated image metadata if an image provider is connected.

```text
id
prompt_generation_id
provider
model_name
image_uri
seed
params_json
status
error_message
created_at
```

### review_actions

Optional in early MVP, useful once review flows become more active.

```text
id
target_type              # character / alias / event / state_change / state
target_id
action_type              # accept / edit / merge / reject
before_json
after_json
actor
note
created_at
```

This table can be added without changing the primary data model.

## State Lifecycle

### Querying CharacterState For Chapter X

When generating a prompt for character C at chapter X, query:

```text
character_id = C
chapter_start <= X
(chapter_end >= X OR chapter_end IS NULL)
status = confirmed
```

If multiple confirmed states match, this is a data integrity problem. The prompt generation service should return a warning or error rather than silently choosing one.

If no confirmed state matches, generation should fail gracefully and ask for state review or creation before producing a formal prompt.

### Creating Initial CharacterState

A character's first state has no previous confirmed CharacterState.

If no previous confirmed state exists, the system can create an initial candidate CharacterState from the chunks around the character's first confirmed appearance.

Initial state rules:

1. `chapter_start` is usually the character's first confirmed appearance chapter, or a chapter manually selected during review.
2. `chapter_end` defaults to null.
3. `event_id` and `state_change_id` can be null.
4. Source chapters and source chunks are still required.
5. The initial state must be reviewed before it becomes confirmed.
6. Prompt generation still fails if no confirmed state covers the requested chapter.

This keeps prompt generation strict while giving StateService a clear path for first appearances.

### Creating Candidate State

The LLM should not directly rewrite a full CharacterState. It outputs CharacterEvent candidates and field-level CharacterStateChange candidates.

The system creates a candidate CharacterState by:

1. Finding the previous confirmed CharacterState for the character.
2. Copying unchanged fields from that state.
3. Applying the field-level changes from CharacterStateChange.
4. Setting `chapter_start = event.chapter_index`.
5. Setting `chapter_end = null`.
6. Setting `status = candidate`.
7. Linking `event_id`, `state_change_id`, `source_chapters`, and `source_chunk_ids`.

### Confirming Candidate State

When a candidate CharacterState is accepted:

1. Mark the candidate state as `confirmed`.
2. Find the previous confirmed state for the same character whose range is active at the new state's `chapter_start`.
3. Set the previous state's `chapter_end = new_state.chapter_start - 1`.
4. Preserve links to the triggering event, state change, source chapters, and source chunks.
5. Record `reviewed_at`, `reviewed_by`, and `review_note`.

This rule keeps state ranges non-overlapping and makes chapter-specific state retrieval deterministic.

### Preventing Overlapping Confirmed States

For the same `novel_id` and `character_id`, confirmed CharacterState ranges must not overlap.

Phase one can enforce this with service-level transactions. A later version can add a PostgreSQL exclusion constraint over normalized chapter ranges.

Confirming a candidate state must happen in a transaction:

1. Lock confirmed states for the same `novel_id` and `character_id`.
2. Find the previous confirmed state whose range contains or precedes the new state's `chapter_start`.
3. Reject the confirmation or route it to manual repair if `new_state.chapter_start <= previous_state.chapter_start`.
4. Close the previous state with `chapter_end = new_state.chapter_start - 1`.
5. Mark the new state as `confirmed`.
6. Check that no confirmed ranges overlap.

If overlap is detected, the transaction should roll back and surface a reviewable integrity error.

## Extraction Flow

Extraction runs at chapter granularity and stores chunk-level evidence.

For each chapter, the extraction input should include:

- Chapter title.
- Chapter summary.
- Main chunks from the chapter.
- Candidate and confirmed characters appearing in the chapter.
- Each involved character's previous confirmed CharacterState.
- Recent confirmed CharacterEvents for those characters.
- Optional previous chapter summary for continuity.

The LLM output should include:

- CharacterEvent candidates.
- For long-term changes, CharacterStateChange candidates.
- `source_chunk_ids` for each event and change.
- Confidence and explanation.

The system should reject or flag outputs that lack chunk evidence.

## Review Flow

The review UI can be simple but must support the knowledge-quality loop.

Required review actions:

- Accept candidate.
- Edit candidate and accept.
- Merge candidates.
- Reject candidate.
- Add review note.

For state changes, the UI should show:

- Previous confirmed state.
- Field-level diff.
- Generated candidate state.
- Source chunks.
- Confidence.
- Explanation.

Only confirmed records can enter prompt generation.

## Prompt Generation

Prompt generation follows this priority order:

1. Confirmed CharacterState is the primary anchor.
2. Current chapter and nearby chunks provide visible scene details.
3. Recent confirmed CharacterEvents explain why the character is in the current state.

CharacterState determines durable character facts:

- Appearance.
- Personality.
- Identity.
- Motivation.
- Relationship summary.
- Visual keywords.
- Negative prompt.

Chunks supplement current scene details:

- Location.
- Action.
- Clothing visible in the scene.
- Injuries visible in the scene.
- Current emotion.
- Lighting.
- Weather.
- Atmosphere.
- Other characters present.

Events provide background constraints and evidence, but they should not all be directly rendered into the image unless visually relevant.

### Conflict Rules

If a current chunk conflicts with CharacterState:

- Explicit current visual description wins for the current prompt, such as "wearing a red robe in this scene".
- Durable facts remain anchored in CharacterState, such as hair color, age range, core identity, and long-term personality.
- The system must save a warning in `prompt_generations.warnings_json`.

Example warning:

```json
{
  "type": "state_chunk_conflict",
  "field": "clothing",
  "state_value": "plain gray robe",
  "chunk_value": "red ceremonial robe",
  "resolution": "used explicit current-scene chunk value"
}
```

Each prompt generation must save:

- CharacterState ID.
- CharacterEvent IDs.
- Chunk IDs.
- Final prompt.
- Negative prompt.
- Model/provider parameters, even if no image is generated.
- Conflict warnings.
- Evidence snapshot.

## Module Boundaries

### ImportService

Converts supported local formats into a normalized book structure:

```text
BookManifest
  title
  author
  source_type
  language
  imported_at
  chapters

Chapter
  chapter_index
  title
  content
  source_path
  word_count
  checksum
```

TXT, EPUB, and Markdown are phase-one import targets. Crawlers can be future adapters that produce the same structure.

### ChunkingService

Splits chapter text by natural paragraphs, aggregates paragraphs into target-size chunks, and records offsets and checksums.

The rest of the system should depend on stored chunks, not on the chunking algorithm. This allows future semantic chunking without changing evidence records.

### EmbeddingRepository And RetrievalService

Own all embedding persistence and vector search.

Business services should not scatter pgvector SQL across the codebase. Future Qdrant migration should primarily replace this boundary.

### CharacterService And AliasService

Own character candidate creation, alias candidate creation, merge suggestions, review status changes, and confirmed alias mapping.

State and event generation should prefer confirmed characters. If a character is not confirmed, extracted related state/event records should remain candidate-only and blocked from formal generation.

### ExtractionService

Runs chapter-level LLM extraction. It produces candidate events and field-level state changes. It does not directly confirm states.

### StateService

Synthesizes full candidate CharacterState snapshots from previous confirmed state plus field-level CharacterStateChange. It also owns state confirmation and previous-state closure rules.

### ReviewService

Provides a consistent accept/edit/merge/reject API across candidates. It can later write review_actions without changing the user-facing workflow.

### PromptGenerationService

Assembles chapter-specific prompt context using the priority order:

```text
confirmed CharacterState
-> relevant current chunks
-> recent confirmed CharacterEvents
```

It also detects conflicts and saves warnings.

### EvidenceService

Assembles source chunks, states, events, and review metadata into evidence bundles for review pages and prompt generation records.

## MVP Implementation Plan

1. Create FastAPI backend foundation, database connection, migrations, and base repository pattern.
2. Define Postgres schema for novels, chapters, chunks, characters, aliases, events, state changes, states, prompt generations, and optional images.
3. Implement TXT and Markdown import adapters first. Add EPUB after the import path is stable.
4. Implement paragraph-preserving chapter chunking.
5. Implement embedding generation and pgvector persistence.
6. Implement RetrievalService for chapter-scoped and semantic chunk retrieval.
7. Implement character and alias candidate extraction and review.
8. Implement chapter-level event and state-change extraction.
9. Implement StateService candidate synthesis from previous state plus field-level changes.
10. Implement initial CharacterState creation for first confirmed character appearances.
11. Implement review confirmation, including previous CharacterState range closure and no-overlap checks.
12. Implement prompt generation for a specified chapter and character.
13. Save full prompt evidence chain, including state ID, event IDs, chunk IDs, warnings, and generation parameters.
14. Build minimal React admin pages for candidate review, state history, and prompt records.
15. Validate with a small book or the first 20-50 chapters of a long novel before processing a full 2-3 million character novel.

## Future Migration Points

### Qdrant

Qdrant can replace pgvector retrieval when text volume or retrieval pressure grows.

The migration point is:

```text
EmbeddingRepository
RetrievalService
```

Postgres should remain the source of truth for novels, chapters, chunks, states, events, and prompt records. Qdrant can store vector indexes and chunk references.

### Neo4j

Neo4j can be introduced when relationships, factions, disguises, and alliance changes become too complex for relational queries.

The migration point is:

```text
CharacterRelationRepository
CharacterGraphService
```

Phase one may store relationship summaries in CharacterState and simple relation records in Postgres. Neo4j should not be introduced until graph traversal becomes a real product need.

### Celery And Redis

Celery and Redis can be added when CLI-driven long tasks need scheduling, retries, cancellation, and progress visibility.

Phase one can run long jobs through CLI commands and keep job metadata simple.

### Image Generation APIs

Image generation providers can be added after prompt quality is stable.

`prompt_generations` should exist before `generated_images`, so prompts and evidence can be audited independently from image API behavior.

## Self-Review

### Scope Check

The MVP stays focused on the evidence-backed prompt generation loop. Crawling, Qdrant, Neo4j, Celery, multi-user workflow, and full image generation are explicitly excluded.

### Status Lifecycle Check

Formal generation requires `status = confirmed` for characters, aliases, events, state changes, and states. Candidate records are review material only.

### CharacterState Lifecycle Check

CharacterState uses chapter ranges. Querying chapter X requires a confirmed state whose range covers X. Confirming a new state closes the previous confirmed state at `new_state.chapter_start - 1`.

Initial CharacterState creation is now covered for first appearances where no previous confirmed state exists.

Confirmed states are required to be non-overlapping per novel and character. Phase one enforces this in StateService transactions, with a future PostgreSQL exclusion constraint available if needed.

### Conflict Check

Current-scene chunk details can override durable state only for explicit visible scene facts. Durable facts remain anchored in CharacterState. Conflicts are saved as warnings on prompt generation records.

### Prompt Scope Check

MVP prompt generation is limited to single-character prompts and simple scene prompts. Group prompts remain future scope because they require additional association modeling.

### Extension Check

Future Qdrant and Neo4j migration points are limited to retrieval and relationship boundaries. The MVP does not introduce full storage plugin abstractions.

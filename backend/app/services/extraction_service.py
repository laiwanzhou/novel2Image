from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import uuid

from app.core.enums import EventType, ReviewStatus
from app.models.character import Character
from app.models.novel import Chapter, ChapterChunk
from app.models.state import CharacterEvent, CharacterStateChange
from app.providers.llm import LlmProvider, LlmProviderResponseError
from app.repositories.characters import CharacterRepository
from app.repositories.chunks import ChunkRepository
from app.repositories.states import StateRepository
from app.services.llm_diagnostics import (
    RawLlmDiagnosticsContext,
    RawLlmResponseDiagnosticsWriter,
    safe_write_raw_llm_failure,
)
from app.services.state_service import STATE_FIELDS, normalize_visual_keywords


ALLOWED_EVENT_TYPES = tuple(event_type.value for event_type in EventType)
ALLOWED_EVENT_TYPES_TEXT = ", ".join(ALLOWED_EVENT_TYPES)


@dataclass(frozen=True)
class ExtractionResult:
    events: list[CharacterEvent]
    state_changes: list[CharacterStateChange]


@dataclass(frozen=True)
class EventDraft:
    character_id: uuid.UUID
    event_summary: str
    event_type: str
    is_long_term_change: bool
    affected_fields: list
    source_chunk_ids: list[str]
    confidence: float | None
    explanation: str | None


@dataclass(frozen=True)
class StateChangeDraft:
    character_id: uuid.UUID
    event_index: int | None
    changed_fields: list[dict]
    source_chunk_ids: list[str]
    confidence: float | None
    explanation: str | None


class ExtractionService:
    def __init__(
        self,
        *,
        state_repository: StateRepository,
        chunk_repository: ChunkRepository,
        character_repository: CharacterRepository,
        llm_provider: LlmProvider,
        auto_confirm_events: bool = False,
        diagnostics_dir: Path | None = None,
    ) -> None:
        self.state_repository = state_repository
        self.chunk_repository = chunk_repository
        self.character_repository = character_repository
        self.llm_provider = llm_provider
        self.auto_confirm_events = auto_confirm_events
        self.diagnostics_writer = RawLlmResponseDiagnosticsWriter(diagnostics_dir)

    def extract_chapter_candidates(self, chapter_id: uuid.UUID) -> ExtractionResult:
        chapter = self.chunk_repository.get_chapter(chapter_id)
        if chapter is None:
            raise ValueError(f"Chapter not found: {chapter_id}")
        chunks = self.chunk_repository.list_chunks_for_chapter(chapter_id)
        allowed_chunk_ids = {str(chunk.id) for chunk in chunks}
        confirmed_characters = self.character_repository.list_characters(
            chapter.novel_id,
            ReviewStatus.CONFIRMED.value,
        )
        system_prompt = self._system_prompt()
        user_prompt = self._user_prompt(chapter=chapter, chunks=chunks, confirmed_characters=confirmed_characters)
        diagnostics_context = RawLlmDiagnosticsContext(
            chapter_id=chapter.id,
            chapter_index=chapter.chapter_index,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            allowed_current_chapter_chunk_ids=sorted(allowed_chunk_ids),
            confirmed_character_ids=sorted(str(character.id) for character in confirmed_characters),
            provider=getattr(self.llm_provider, "provider_name", None),
            model=getattr(self.llm_provider, "model", None),
        )
        try:
            response = self.llm_provider.generate_json(system_prompt, user_prompt)
            event_drafts, state_change_drafts = self._validate_response(
                response=response,
                allowed_chunk_ids=allowed_chunk_ids,
            )
        except LlmProviderResponseError as exc:
            safe_write_raw_llm_failure(
                self.diagnostics_writer,
                context=diagnostics_context,
                error=exc,
                raw_response_text=exc.raw_response,
                raw_parsed_response=exc.parsed_response,
            )
            raise
        except ValueError as exc:
            raw_parsed_response = locals().get("response")
            safe_write_raw_llm_failure(
                self.diagnostics_writer,
                context=diagnostics_context,
                error=exc,
                raw_parsed_response=raw_parsed_response if isinstance(raw_parsed_response, dict) else None,
            )
            raise
        return self._persist_validated_response(
            chapter=chapter,
            event_drafts=event_drafts,
            state_change_drafts=state_change_drafts,
        )

    def _validate_response(
        self,
        *,
        response: dict,
        allowed_chunk_ids: set[str],
    ) -> tuple[list[EventDraft], list[StateChangeDraft]]:
        raw_events = response.get("events", [])
        raw_state_changes = response.get("state_changes", [])
        if not isinstance(raw_events, list) or not isinstance(raw_state_changes, list):
            raise ValueError("LLM extraction response must contain events and state_changes lists")

        event_drafts: list[EventDraft] = []
        for raw_event in raw_events:
            source_chunk_ids = self._require_source_chunks(raw_event, "event", allowed_chunk_ids)
            character = self._require_confirmed_character(raw_event.get("character_id"))
            event_drafts.append(
                EventDraft(
                    character_id=character.id,
                    event_summary=self._require_string(raw_event, "event_summary"),
                    event_type=self._require_event_type(raw_event),
                    is_long_term_change=bool(raw_event.get("is_long_term_change", False)),
                    affected_fields=list(raw_event.get("affected_fields", [])),
                    source_chunk_ids=source_chunk_ids,
                    confidence=raw_event.get("confidence"),
                    explanation=raw_event.get("explanation"),
                )
            )

        state_change_drafts: list[StateChangeDraft] = []
        for raw_change in raw_state_changes:
            source_chunk_ids = self._require_source_chunks(raw_change, "state_change", allowed_chunk_ids)
            character = self._require_confirmed_character(raw_change.get("character_id"))
            event_index = self._validated_event_index(raw_change, event_drafts)
            if event_index is None:
                raise ValueError("state_change requires event_index referencing a long-term event")
            if not event_drafts[event_index].is_long_term_change:
                raise ValueError("state_change event_index must reference an event with is_long_term_change=true")
            changed_fields = self._require_changed_fields(raw_change, allowed_chunk_ids)
            state_change_drafts.append(
                StateChangeDraft(
                    character_id=character.id,
                    event_index=event_index,
                    changed_fields=changed_fields,
                    source_chunk_ids=source_chunk_ids,
                    confidence=raw_change.get("confidence"),
                    explanation=self._require_state_change_explanation(raw_change),
                )
            )

        return event_drafts, state_change_drafts

    def _persist_validated_response(
        self,
        *,
        chapter: Chapter,
        event_drafts: list[EventDraft],
        state_change_drafts: list[StateChangeDraft],
    ) -> ExtractionResult:
        with self.state_repository.session.begin_nested():
            events: list[CharacterEvent] = []
            for draft in event_drafts:
                event_status = ReviewStatus.CONFIRMED.value if self.auto_confirm_events else ReviewStatus.CANDIDATE.value
                event = CharacterEvent(
                    novel_id=chapter.novel_id,
                    character_id=draft.character_id,
                    chapter_id=chapter.id,
                    chapter_index=chapter.chapter_index,
                    event_summary=draft.event_summary,
                    event_type=draft.event_type,
                    is_long_term_change=draft.is_long_term_change,
                    affected_fields=draft.affected_fields,
                    source_chunk_ids=draft.source_chunk_ids,
                    confidence=draft.confidence,
                    explanation=draft.explanation,
                    status=event_status,
                    reviewed_at=datetime.now(UTC) if self.auto_confirm_events else None,
                    reviewed_by="auto-extraction" if self.auto_confirm_events else None,
                    review_note="auto-confirmed after extraction validation" if self.auto_confirm_events else None,
                )
                events.append(self.state_repository.add_event(event))

            state_changes: list[CharacterStateChange] = []
            for draft in state_change_drafts:
                event = events[draft.event_index] if draft.event_index is not None else None
                state_change = CharacterStateChange(
                    novel_id=chapter.novel_id,
                    character_id=draft.character_id,
                    event_id=event.id if event is not None else None,
                    chapter_id=chapter.id,
                    chapter_index=chapter.chapter_index,
                    changed_fields=draft.changed_fields,
                    source_chunk_ids=draft.source_chunk_ids,
                    confidence=draft.confidence,
                    explanation=draft.explanation,
                    status=ReviewStatus.CANDIDATE.value,
                )
                state_changes.append(self.state_repository.add_state_change(state_change))

        return ExtractionResult(events=events, state_changes=state_changes)

    def _validated_event_index(self, raw_change: dict, events: list[EventDraft]) -> int | None:
        event_index = raw_change.get("event_index")
        if event_index is None:
            return None
        if not isinstance(event_index, int) or event_index < 0 or event_index >= len(events):
            raise ValueError("state_change event_index does not reference an extracted event")
        return event_index

    def _require_confirmed_character(self, character_id) -> Character:
        try:
            parsed_id = uuid.UUID(str(character_id))
        except (TypeError, ValueError) as exc:
            raise ValueError("Extraction output must reference a valid confirmed character") from exc
        character = self.character_repository.get_character(parsed_id)
        if character is None or character.status != ReviewStatus.CONFIRMED.value:
            raise ValueError("Extraction output must reference a confirmed character")
        return character

    def _require_source_chunks(self, raw: dict, label: str, allowed_chunk_ids: set[str]) -> list[str]:
        source_chunk_ids = raw.get("source_chunk_ids")
        if not isinstance(source_chunk_ids, list) or not source_chunk_ids:
            raise ValueError(f"{label} requires non-empty source_chunk_ids")
        parsed_ids: list[str] = []
        for chunk_id in source_chunk_ids:
            try:
                parsed_id = str(uuid.UUID(str(chunk_id)))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{label} source_chunk_ids must contain valid chunk UUIDs") from exc
            if parsed_id not in allowed_chunk_ids:
                raise ValueError(f"{label} source_chunk_ids must reference chunks from the current chapter")
            parsed_ids.append(parsed_id)
        return parsed_ids

    def _require_string(self, raw: dict, field: str) -> str:
        value = raw.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"Extraction output requires string field: {field}")
        return value

    def _require_event_type(self, raw_event: dict) -> str:
        event_type = raw_event.get("event_type", EventType.OTHER.value)
        if event_type not in ALLOWED_EVENT_TYPES:
            raise ValueError(
                f"Invalid event_type from LLM: {event_type}. Allowed values: {ALLOWED_EVENT_TYPES_TEXT}"
            )
        return event_type

    def _require_changed_fields(self, raw_change: dict, allowed_chunk_ids: set[str]) -> list[dict]:
        changed_fields = raw_change.get("changed_fields")
        if not isinstance(changed_fields, list) or not changed_fields:
            raise ValueError("state_change requires non-empty changed_fields")
        for change in changed_fields:
            if not isinstance(change, dict) or "field" not in change or "after" not in change:
                raise ValueError("Each changed field requires field and after")
            if change["field"] not in STATE_FIELDS:
                raise ValueError(f"Invalid changed field from LLM: {change['field']}")
            if change["field"] == "visual_keywords":
                change["after"] = normalize_visual_keywords(change.get("after")) or []
                if "before" in change:
                    change["before"] = normalize_visual_keywords(change.get("before")) or []
            change["source_chunk_ids"] = self._require_source_chunks(change, "changed_field", allowed_chunk_ids)
        return changed_fields

    def _require_state_change_explanation(self, raw_change: dict) -> str:
        explanation = raw_change.get("explanation")
        if not isinstance(explanation, str) or not explanation.strip():
            raise ValueError("state_change requires explanation describing why the change is long-term")
        return explanation

    def _system_prompt(self) -> str:
        return """
You extract auditable novel character knowledge. Return strict JSON only.

The JSON object must use exactly these top-level keys:
{
  "events": [
    {
      "character_id": "confirmed character_id copied exactly from confirmed_characters",
      "chapter_index": 1,
      "event_summary": "brief event grounded in the chapter text",
      "event_type": "appearance|identity|relationship|motivation|other",
      "is_long_term_change": true,
      "affected_fields": ["motivation"],
      "source_chunk_ids": ["chunk UUID copied exactly from chunks"],
      "confidence": 0.0,
      "explanation": "short evidence explanation"
    }
  ],
  "state_changes": [
    {
      "character_id": "confirmed character_id copied exactly from confirmed_characters",
      "event_index": 0,
      "changed_fields": [
        {
          "field": "appearance|personality|identity|motivation|relationship_summary|visual_keywords|negative_prompt",
          "before": null,
          "after": "new long-term value supported by evidence",
          "source_chunk_ids": ["chunk UUID copied exactly from chunks"]
        }
      ],
      "source_chunk_ids": ["chunk UUID copied exactly from chunks"],
      "confidence": 0.0,
      "explanation": "why this is a long-term change"
    }
  ]
}

Rules:
- Output valid json only, with no markdown and no extra top-level keys.
- Use only confirmed character_id values from confirmed_characters.
- Every event, state_change, and changed_field must include non-empty source_chunk_ids.
- source_chunk_ids must be copied exactly from the provided chunks for the current chapter.
- If there is no supported event or long-term state change, output empty arrays.
- CharacterEvent can describe ordinary plot events, but CharacterStateChange is only for durable changes that should affect later chapters.
- Every state_change must set event_index to a related event whose is_long_term_change is true.
- If an event is not long-term, do not create a state_change for it.
- Every state_change explanation must explain why the change is durable rather than temporary.
- Do not create state_changes for a momentary emotion, action, pose, location, or dialogue.
- Accepting a new name, forming a long-term partnership, or establishing a rebuilding goal can be identity, relationship, or motivation changes when source chunks support that durability.
- Use event_type other for discoveries, actions, battles, and dialogue.
- Use event_type motivation only when evidence supports a motivation change.
- Do not create state_changes for temporary states, poses, scene movement, one-off dialogue, or momentary lighting.
- Do not invent facts that are not supported by source chunks.
""".strip()

    def _user_prompt(
        self,
        *,
        chapter: Chapter,
        chunks: list[ChapterChunk],
        confirmed_characters: list[Character],
    ) -> str:
        payload = {
            "chapter": {
                "id": str(chapter.id),
                "title": chapter.title,
                "summary": chapter.summary,
                "chapter_index": chapter.chapter_index,
            },
            "confirmed_characters": [
                {
                    "id": str(character.id),
                    "canonical_name": character.canonical_name,
                    "description": character.description,
                }
                for character in confirmed_characters
            ],
            "chunks": [
                {
                    "id": str(chunk.id),
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                }
                for chunk in chunks
            ],
        }
        return (
            "Return only a valid JSON object with exactly the top-level keys "
            '"events" and "state_changes". Do not return empty content. '
            "Use the following chapter payload as evidence:\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

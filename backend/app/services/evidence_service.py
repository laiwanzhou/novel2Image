import uuid

from app.repositories.chunks import ChunkRepository
from app.repositories.states import StateRepository
from app.schemas.prompt_schema import EvidenceBundle, EvidenceChunk, EvidenceEvent, EvidenceState


class EvidenceService:
    def __init__(
        self,
        *,
        state_repository: StateRepository,
        chunk_repository: ChunkRepository,
    ) -> None:
        self.state_repository = state_repository
        self.chunk_repository = chunk_repository

    def build_bundle(
        self,
        *,
        state_id: uuid.UUID | None,
        event_ids: list[uuid.UUID],
        chunk_ids: list[uuid.UUID],
    ) -> dict:
        state = self.state_repository.get_state(state_id) if state_id is not None else None
        events = self.state_repository.list_events_by_ids(event_ids)
        chunks = self.chunk_repository.list_chunks_by_ids(chunk_ids)
        self._require_all_found(
            requested_ids=event_ids,
            found_ids=[event.id for event in events],
            label="Event evidence",
        )
        self._require_all_found(
            requested_ids=chunk_ids,
            found_ids=[chunk.id for chunk in chunks],
            label="Chunk evidence",
        )
        bundle = EvidenceBundle(
            state=EvidenceState(
                id=str(state.id),
                character_id=str(state.character_id),
                chapter_start=state.chapter_start,
                chapter_end=state.chapter_end,
                appearance=state.appearance,
                personality=state.personality,
                identity=state.identity,
                motivation=state.motivation,
                relationship_summary=state.relationship_summary,
                visual_keywords=state.visual_keywords,
                negative_prompt=state.negative_prompt,
                source_chapters=state.source_chapters,
                source_chunk_ids=state.source_chunk_ids,
                confidence=state.confidence,
            )
            if state is not None
            else None,
            events=[
                EvidenceEvent(
                    id=str(event.id),
                    character_id=str(event.character_id) if event.character_id is not None else None,
                    chapter_index=event.chapter_index,
                    event_summary=event.event_summary,
                    event_type=event.event_type,
                    affected_fields=event.affected_fields,
                    source_chunk_ids=event.source_chunk_ids,
                    confidence=event.confidence,
                    explanation=event.explanation,
                )
                for event in events
            ],
            chunks=[
                EvidenceChunk(
                    id=str(chunk.id),
                    chapter_id=str(chunk.chapter_id),
                    chapter_index=chunk.chapter_index,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    start_char=chunk.start_char,
                    end_char=chunk.end_char,
                    checksum=chunk.checksum,
                )
                for chunk in chunks
            ],
        )
        return bundle.model_dump()

    def _require_all_found(
        self,
        *,
        requested_ids: list[uuid.UUID],
        found_ids: list[uuid.UUID],
        label: str,
    ) -> None:
        requested = {str(requested_id) for requested_id in requested_ids}
        found = {str(found_id) for found_id in found_ids}
        missing = sorted(requested - found)
        if missing:
            raise ValueError(f"{label} not found: {', '.join(missing)}")

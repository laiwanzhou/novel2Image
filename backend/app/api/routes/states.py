import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.repositories.states import StateRepository
from app.schemas.review_schema import CharacterStateFields
from app.services.state_service import StateService


router = APIRouter(prefix="/characters", tags=["states"])
state_router = APIRouter(prefix="/states", tags=["states"])


class InitialStateRequest(BaseModel):
    novel_id: uuid.UUID
    chapter_start: int
    source_chunk_ids: list[str]
    fields: CharacterStateFields
    confidence: float | None = None


class ConfirmStateRequest(BaseModel):
    reviewer: str = "api"
    note: str | None = None


@router.get("/{character_id}/states")
def list_states(character_id: uuid.UUID, db: Session = Depends(get_db)) -> list[dict]:
    return [_state_response(state) for state in StateRepository(db).list_states_for_character(character_id)]


@router.post("/{character_id}/initial-state")
def create_initial_state(
    character_id: uuid.UUID,
    request: InitialStateRequest,
    db: Session = Depends(get_db),
) -> dict:
    state = StateService(StateRepository(db)).create_initial_state_candidate(
        novel_id=request.novel_id,
        character_id=character_id,
        chapter_start=request.chapter_start,
        source_chunk_ids=request.source_chunk_ids,
        fields=request.fields,
        confidence=request.confidence,
    )
    db.commit()
    return _state_response(state)


@state_router.post("/{state_id}/confirm")
def confirm_state(
    state_id: uuid.UUID,
    request: ConfirmStateRequest,
    db: Session = Depends(get_db),
) -> dict:
    state = StateService(StateRepository(db)).confirm_state(state_id, request.reviewer, request.note)
    db.commit()
    return _state_response(state)


def _state_response(state) -> dict:
    return {
        "id": str(state.id),
        "novel_id": str(state.novel_id),
        "character_id": str(state.character_id),
        "chapter_start": state.chapter_start,
        "chapter_end": state.chapter_end,
        "appearance": state.appearance,
        "personality": state.personality,
        "identity": state.identity,
        "motivation": state.motivation,
        "relationship_summary": state.relationship_summary,
        "visual_keywords": state.visual_keywords,
        "negative_prompt": state.negative_prompt,
        "source_chapters": state.source_chapters,
        "source_chunk_ids": state.source_chunk_ids,
        "confidence": state.confidence,
        "status": state.status,
        "reviewed_at": state.reviewed_at,
        "reviewed_by": state.reviewed_by,
        "review_note": state.review_note,
    }

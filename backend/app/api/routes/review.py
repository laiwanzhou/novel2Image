import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.character import Character, CharacterAlias
from app.models.state import CharacterEvent, CharacterStateChange
from app.repositories.characters import CharacterRepository
from app.repositories.states import StateRepository
from app.services.character_service import CharacterService
from app.services.state_service import StateService


router = APIRouter(prefix="/review", tags=["review"])


class ReviewRequest(BaseModel):
    reviewer: str = "api"
    note: str | None = None


class ConfirmAliasRequest(ReviewRequest):
    character_id: uuid.UUID


@router.get("/candidates")
def list_candidates(novel_id: uuid.UUID, db: Session = Depends(get_db)) -> list[dict]:
    candidates = CharacterRepository(db).list_candidates(novel_id)
    return [_candidate_response(candidate) for candidate in candidates]


@router.get("/events")
def list_event_candidates(
    novel_id: uuid.UUID,
    chapter_id: uuid.UUID | None = None,
    character_id: uuid.UUID | None = None,
    status: str | None = "candidate",
    db: Session = Depends(get_db),
) -> list[dict]:
    _validate_status_filter(status)
    repository = StateRepository(db)
    events = repository.list_events(
        novel_id=novel_id,
        chapter_id=chapter_id,
        character_id=character_id,
        status=status,
    )
    return [_event_response(db, event) for event in events]


@router.post("/events/{event_id}/accept")
def accept_event_candidate(
    event_id: uuid.UUID,
    request: ReviewRequest,
    db: Session = Depends(get_db),
) -> dict:
    event = StateService(StateRepository(db)).confirm_event(event_id, request.reviewer, request.note)
    db.commit()
    return _event_response(db, event)


@router.post("/events/{event_id}/reject")
def reject_event_candidate(
    event_id: uuid.UUID,
    request: ReviewRequest,
    db: Session = Depends(get_db),
) -> dict:
    event = StateService(StateRepository(db)).reject_event(event_id, request.reviewer, request.note)
    db.commit()
    return _event_response(db, event)


@router.get("/state-changes")
def list_state_change_candidates(
    novel_id: uuid.UUID,
    chapter_id: uuid.UUID | None = None,
    character_id: uuid.UUID | None = None,
    status: str | None = "candidate",
    db: Session = Depends(get_db),
) -> list[dict]:
    _validate_status_filter(status)
    repository = StateRepository(db)
    state_changes = repository.list_state_changes(
        novel_id=novel_id,
        chapter_id=chapter_id,
        character_id=character_id,
        status=status,
    )
    return [_state_change_response(db, state_change) for state_change in state_changes]


@router.post("/state-changes/{state_change_id}/accept")
def accept_state_change_candidate(
    state_change_id: uuid.UUID,
    request: ReviewRequest,
    db: Session = Depends(get_db),
) -> dict:
    state_change = StateService(StateRepository(db)).confirm_state_change(state_change_id, request.reviewer, request.note)
    db.commit()
    return _state_change_response(db, state_change)


@router.post("/state-changes/{state_change_id}/reject")
def reject_state_change_candidate(
    state_change_id: uuid.UUID,
    request: ReviewRequest,
    db: Session = Depends(get_db),
) -> dict:
    state_change = StateService(StateRepository(db)).reject_state_change(state_change_id, request.reviewer, request.note)
    db.commit()
    return _state_change_response(db, state_change)


@router.post("/{target_type}/{target_id}/accept")
def accept_candidate(
    target_type: str,
    target_id: uuid.UUID,
    request: ReviewRequest,
    db: Session = Depends(get_db),
) -> dict:
    if target_type != "character":
        raise ValueError(f"Unsupported accept target type: {target_type}")
    target = CharacterService(CharacterRepository(db)).confirm_character(target_id, request.reviewer, request.note)
    db.commit()
    return _candidate_response(target)


@router.post("/{target_type}/{target_id}/reject")
def reject_candidate(
    target_type: str,
    target_id: uuid.UUID,
    request: ReviewRequest,
    db: Session = Depends(get_db),
) -> dict:
    target = CharacterService(CharacterRepository(db)).reject_candidate(target_type, target_id, request.reviewer, request.note)
    db.commit()
    return _candidate_response(target)


@router.post("/aliases/{alias_id}/confirm")
def confirm_alias(
    alias_id: uuid.UUID,
    request: ConfirmAliasRequest,
    db: Session = Depends(get_db),
) -> dict:
    alias = CharacterService(CharacterRepository(db)).confirm_alias(
        alias_id,
        request.character_id,
        request.reviewer,
        request.note,
    )
    db.commit()
    return _candidate_response(alias)


def _candidate_response(candidate: Character | CharacterAlias) -> dict:
    if isinstance(candidate, Character):
        return {
            "target_type": "character",
            "id": str(candidate.id),
            "novel_id": str(candidate.novel_id),
            "label": candidate.canonical_name,
            "status": candidate.status,
            "source_chunk_ids": candidate.source_chunk_ids,
            "confidence": candidate.confidence,
            "review_note": candidate.review_note,
        }
    return {
        "target_type": "alias",
        "id": str(candidate.id),
        "novel_id": str(candidate.novel_id),
        "character_id": str(candidate.character_id) if candidate.character_id is not None else None,
        "label": candidate.alias_text,
        "alias_type": candidate.alias_type,
        "status": candidate.status,
        "source_chunk_ids": candidate.source_chunk_ids,
        "confidence": candidate.confidence,
        "review_note": candidate.review_note,
    }


def _event_response(db: Session, event: CharacterEvent) -> dict:
    character = db.get(Character, event.character_id) if event.character_id is not None else None
    return {
        "id": str(event.id),
        "novel_id": str(event.novel_id),
        "character_id": str(event.character_id) if event.character_id is not None else None,
        "character_name": character.canonical_name if character is not None else None,
        "chapter_id": str(event.chapter_id),
        "chapter_index": event.chapter_index,
        "event_summary": event.event_summary,
        "event_type": event.event_type,
        "is_long_term_change": event.is_long_term_change,
        "affected_fields": event.affected_fields,
        "source_chunk_ids": event.source_chunk_ids,
        "confidence": event.confidence,
        "explanation": event.explanation,
        "status": event.status,
        "reviewed_at": event.reviewed_at,
        "reviewed_by": event.reviewed_by,
        "review_note": event.review_note,
    }


def _state_change_response(db: Session, state_change: CharacterStateChange) -> dict:
    character = db.get(Character, state_change.character_id) if state_change.character_id is not None else None
    return {
        "id": str(state_change.id),
        "novel_id": str(state_change.novel_id),
        "character_id": str(state_change.character_id) if state_change.character_id is not None else None,
        "character_name": character.canonical_name if character is not None else None,
        "event_id": str(state_change.event_id) if state_change.event_id is not None else None,
        "chapter_id": str(state_change.chapter_id),
        "chapter_index": state_change.chapter_index,
        "changed_fields": state_change.changed_fields,
        "source_chunk_ids": state_change.source_chunk_ids,
        "confidence": state_change.confidence,
        "explanation": state_change.explanation,
        "status": state_change.status,
        "reviewed_at": state_change.reviewed_at,
        "reviewed_by": state_change.reviewed_by,
        "review_note": state_change.review_note,
    }


def _validate_status_filter(status: str | None) -> None:
    if status is None:
        return
    if status not in {"candidate", "confirmed", "rejected"}:
        raise ValueError("Unsupported review status filter")

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.character import Character, CharacterAlias
from app.repositories.characters import CharacterRepository
from app.services.character_service import CharacterService


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

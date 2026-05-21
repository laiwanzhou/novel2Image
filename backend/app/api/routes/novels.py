import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
from app.core.enums import ReviewStatus
from app.providers.embeddings import get_embedding_provider
from app.repositories.characters import CharacterRepository
from app.repositories.chunks import ChunkRepository
from app.repositories.novels import NovelRepository
from app.repositories.prompts import PromptRepository
from app.repositories.states import StateRepository
from app.services.character_service import CharacterService
from app.services.chunking_service import ChunkingService
from app.services.embedding_service import EmbeddingService


router = APIRouter(prefix="/novels", tags=["novels"])

CHARACTER_STATUS_FILTERS = {
    ReviewStatus.CANDIDATE.value,
    ReviewStatus.CONFIRMED.value,
    ReviewStatus.REJECTED.value,
    "all",
}

CHUNK_REBUILD_BLOCKED_MESSAGE = (
    "This novel already has chunk-based knowledge or prompt records. "
    "Workspace chunk rebuild is blocked; use a CLI/database rebuild flow "
    "or a future dedicated rebuild workflow."
)


class ChunkNovelRequest(BaseModel):
    target_chars: int = 1200
    max_chars: int = 1500


class EmbedNovelRequest(BaseModel):
    batch_size: int = 64


class CreateCharacterRequest(BaseModel):
    canonical_name: str
    description: str | None = None
    status: str = ReviewStatus.CANDIDATE.value
    source_chunk_ids: list[str] = []
    confidence: float | None = None


@router.get("/{novel_id}")
def get_novel(novel_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    novel = NovelRepository(db).get_novel(novel_id)
    if novel is None:
        raise ValueError(f"Novel not found: {novel_id}")
    return {
        "id": str(novel.id),
        "title": novel.title,
        "author": novel.author,
        "source_type": novel.source_type,
        "language": novel.language,
        "imported_at": novel.imported_at,
        "created_at": novel.created_at,
    }


@router.get("/{novel_id}/chapters")
def list_chapters(novel_id: uuid.UUID, db: Session = Depends(get_db)) -> list[dict]:
    summaries = NovelRepository(db).list_chapter_summaries(novel_id)
    return [
        {
            "id": str(summary.id),
            "title": summary.title,
            "chapter_index": summary.chapter_index,
            "word_count": summary.word_count,
            "chunk_count": summary.chunk_count,
            "embedded_count": summary.embedded_count,
        }
        for summary in summaries
    ]


@router.get("/{novel_id}/processing-status")
def processing_status(novel_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    novel_repository = NovelRepository(db)
    chunk_repository = ChunkRepository(db)
    character_repository = CharacterRepository(db)
    state_repository = StateRepository(db)
    prompt_repository = PromptRepository(db)
    chunk_count = chunk_repository.count_chunks_for_novel(novel_id)
    embedded_count = chunk_repository.count_embedded_chunks_for_novel(novel_id)
    return {
        "novel_id": str(novel_id),
        "chapter_count": novel_repository.count_chapters(novel_id),
        "chunk_count": chunk_count,
        "embedded_count": embedded_count,
        "missing_embedding_count": chunk_count - embedded_count,
        "candidate_character_count": character_repository.count_characters(novel_id, ReviewStatus.CANDIDATE.value),
        "confirmed_character_count": character_repository.count_characters(novel_id, ReviewStatus.CONFIRMED.value),
        "candidate_alias_count": character_repository.count_aliases(novel_id, ReviewStatus.CANDIDATE.value),
        "candidate_event_count": state_repository.count_events(novel_id, ReviewStatus.CANDIDATE.value),
        "candidate_state_change_count": state_repository.count_state_changes(novel_id, ReviewStatus.CANDIDATE.value),
        "candidate_state_count": state_repository.count_states(novel_id, ReviewStatus.CANDIDATE.value),
        "confirmed_state_count": state_repository.count_states(novel_id, ReviewStatus.CONFIRMED.value),
        "prompt_generation_count": prompt_repository.count_prompt_generations(novel_id),
    }


@router.get("/{novel_id}/characters")
def list_characters(
    novel_id: uuid.UUID,
    status: str = ReviewStatus.CONFIRMED.value,
    db: Session = Depends(get_db),
) -> list[dict]:
    if status not in CHARACTER_STATUS_FILTERS:
        raise ValueError(f"Unsupported character status filter: {status}")
    characters = CharacterRepository(db).list_characters(
        novel_id,
        None if status == "all" else status,
    )
    return [
        {
            "id": str(character.id),
            "novel_id": str(character.novel_id),
            "canonical_name": character.canonical_name,
            "status": character.status,
            "description": character.description,
            "confidence": character.confidence,
        }
        for character in characters
    ]


@router.post("/{novel_id}/characters")
def create_character(novel_id: uuid.UUID, request: CreateCharacterRequest, db: Session = Depends(get_db)) -> dict:
    if request.status not in {ReviewStatus.CANDIDATE.value, ReviewStatus.CONFIRMED.value}:
        raise ValueError("Character status must be candidate or confirmed")
    if NovelRepository(db).get_novel(novel_id) is None:
        raise ValueError(f"Novel not found: {novel_id}")

    service = CharacterService(CharacterRepository(db))
    character = service.create_character_candidate(
        novel_id=novel_id,
        canonical_name=request.canonical_name,
        source_chunk_ids=request.source_chunk_ids,
        confidence=request.confidence,
        description=request.description,
    )
    if request.status == ReviewStatus.CONFIRMED.value:
        character = service.confirm_character(character.id, reviewer="workspace", note="manual workspace create")
    db.commit()
    return _character_summary(character)


@router.post("/{novel_id}/chunk")
def chunk_novel(novel_id: uuid.UUID, request: ChunkNovelRequest, db: Session = Depends(get_db)) -> dict:
    novel_repository = NovelRepository(db)
    character_repository = CharacterRepository(db)
    state_repository = StateRepository(db)
    prompt_repository = PromptRepository(db)

    chapters = novel_repository.list_chapters(novel_id)
    if not chapters and novel_repository.get_novel(novel_id) is None:
        raise ValueError(f"Novel not found: {novel_id}")
    if (
        character_repository.has_chunk_evidence_candidates(novel_id)
        or state_repository.has_events_or_states_for_novel(novel_id)
        or prompt_repository.has_prompt_generations(novel_id)
    ):
        raise ValueError(CHUNK_REBUILD_BLOCKED_MESSAGE)

    chunk_repository = ChunkRepository(db)
    chunker = ChunkingService()
    chunk_count = 0
    for chapter in chapters:
        chunks = chunker.chunk_chapter(
            chapter.content,
            target_chars=request.target_chars,
            max_chars=request.max_chars,
        )
        chunk_repository.replace_chunks_for_chapter(
            novel_id=chapter.novel_id,
            chapter_id=chapter.id,
            chapter_index=chapter.chapter_index,
            chunks=chunks,
        )
        chunk_count += len(chunks)
    db.commit()
    return {
        "novel_id": str(novel_id),
        "chapter_count": len(chapters),
        "chunk_count": chunk_count,
        "replaced_existing_chunks": True,
    }


@router.post("/{novel_id}/embed")
def embed_novel(novel_id: uuid.UUID, request: EmbedNovelRequest, db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    chunk_repository = ChunkRepository(db)
    provider = get_embedding_provider(settings.embedding_provider)
    embedded_count = EmbeddingService(chunk_repository, provider).embed_missing_chunks(
        novel_id,
        batch_size=request.batch_size,
    )
    remaining_missing = chunk_repository.count_chunks_for_novel(novel_id) - chunk_repository.count_embedded_chunks_for_novel(novel_id)
    db.commit()
    return {
        "novel_id": str(novel_id),
        "embedded_count": embedded_count,
        "remaining_missing_embedding_count": remaining_missing,
        "provider": settings.embedding_provider,
    }


def _character_summary(character) -> dict:
    return {
        "id": str(character.id),
        "novel_id": str(character.novel_id),
        "canonical_name": character.canonical_name,
        "status": character.status,
        "description": character.description,
        "source_chunk_ids": character.source_chunk_ids,
        "confidence": character.confidence,
        "reviewed_by": character.reviewed_by,
        "review_note": character.review_note,
    }

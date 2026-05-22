import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
from app.providers.llm import get_llm_provider
from app.repositories.characters import CharacterRepository
from app.repositories.chunks import ChunkRepository
from app.repositories.states import StateRepository
from app.services.extraction_service import ExtractionService


router = APIRouter(prefix="/chapters", tags=["chapters"])


@router.get("/{chapter_id}/chunks")
def list_chapter_chunks(chapter_id: uuid.UUID, db: Session = Depends(get_db)) -> list[dict]:
    chunks = ChunkRepository(db).list_chunk_previews_for_chapter(chapter_id)
    return [
        {
            "id": str(chunk.id),
            "novel_id": str(chunk.novel_id),
            "chapter_id": str(chunk.chapter_id),
            "chapter_index": chunk.chapter_index,
            "chunk_index": chunk.chunk_index,
            "char_count": chunk.char_count,
            "token_count": chunk.token_count,
            "has_embedding": chunk.embedding is not None,
            "text_preview": chunk.text[:240],
        }
        for chunk in chunks
    ]


@router.post("/{chapter_id}/extract")
def extract_chapter(chapter_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    result = ExtractionService(
        state_repository=StateRepository(db),
        chunk_repository=ChunkRepository(db),
        character_repository=CharacterRepository(db),
        llm_provider=get_llm_provider(
            settings.llm_provider,
            api_base=settings.llm_api_base,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            json_mode=settings.llm_json_mode,
            max_tokens=settings.llm_max_tokens,
            timeout_seconds=settings.llm_timeout_seconds,
        ),
    ).extract_chapter_candidates(chapter_id)
    chapter = ChunkRepository(db).get_chapter(chapter_id)
    if chapter is None:
        raise ValueError(f"Chapter not found: {chapter_id}")
    db.commit()
    return {
        "chapter_id": str(chapter.id),
        "chapter_index": chapter.chapter_index,
        "event_candidate_count": len(result.events),
        "state_change_candidate_count": len(result.state_changes),
    }

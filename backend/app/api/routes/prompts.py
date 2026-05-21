import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.repositories.chunks import ChunkRepository
from app.repositories.prompts import PromptRepository
from app.repositories.states import StateRepository
from app.services.evidence_service import EvidenceService
from app.services.prompt_generation_service import PromptGenerationService


router = APIRouter(prefix="/prompts", tags=["prompts"])


class GeneratePromptRequest(BaseModel):
    novel_id: uuid.UUID
    chapter_index: int
    character_id: uuid.UUID
    user_request: str | None = None


@router.post("/generate")
def generate_prompt(request: GeneratePromptRequest, db: Session = Depends(get_db)) -> dict:
    state_repository = StateRepository(db)
    chunk_repository = ChunkRepository(db)
    prompt = PromptGenerationService(
        state_repository=state_repository,
        chunk_repository=chunk_repository,
        prompt_repository=PromptRepository(db),
        evidence_service=EvidenceService(
            state_repository=state_repository,
            chunk_repository=chunk_repository,
        ),
    ).generate_character_prompt(
        novel_id=request.novel_id,
        chapter_index=request.chapter_index,
        character_id=request.character_id,
        user_request=request.user_request,
    )
    db.commit()
    return _prompt_response(prompt)


@router.get("/history")
def prompt_history(novel_id: uuid.UUID, db: Session = Depends(get_db)) -> list[dict]:
    prompts = PromptRepository(db).list_prompt_generations(novel_id)
    return [_prompt_response(prompt) for prompt in prompts]


@router.get("/{prompt_generation_id}")
def prompt_detail(prompt_generation_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    prompt = PromptRepository(db).get_prompt_generation(prompt_generation_id)
    if prompt is None:
        raise ValueError(f"PromptGeneration not found: {prompt_generation_id}")
    return _prompt_response(prompt)


def _prompt_response(prompt) -> dict:
    return {
        "id": str(prompt.id),
        "novel_id": str(prompt.novel_id),
        "chapter_id": str(prompt.chapter_id),
        "chapter_index": prompt.chapter_index,
        "character_id": str(prompt.character_id) if prompt.character_id is not None else None,
        "character_state_id": str(prompt.character_state_id) if prompt.character_state_id is not None else None,
        "prompt_type": prompt.prompt_type,
        "user_request": prompt.user_request,
        "final_prompt": prompt.final_prompt,
        "negative_prompt": prompt.negative_prompt,
        "model_provider": prompt.model_provider,
        "model_name": prompt.model_name,
        "model_params": prompt.model_params,
        "used_event_ids": prompt.used_event_ids,
        "used_chunk_ids": prompt.used_chunk_ids,
        "warnings": prompt.warnings,
        "evidence_snapshot": prompt.evidence_snapshot,
    }

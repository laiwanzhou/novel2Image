from pathlib import Path

from sqlalchemy.orm import Session

from app.core.enums import EventType, ReviewStatus
from app.models.state import CharacterEvent, CharacterStateChange
from app.providers.embeddings import FakeEmbeddingProvider
from app.repositories.characters import CharacterRepository
from app.repositories.chunks import ChunkRepository
from app.repositories.novels import NovelRepository
from app.repositories.prompts import PromptRepository
from app.repositories.states import StateRepository
from app.schemas.review_schema import CharacterStateFields
from app.services.character_service import CharacterService
from app.services.chunking_service import ChunkingService
from app.services.embedding_service import EmbeddingService
from app.services.evidence_service import EvidenceService
from app.services.import_service import ImportService
from app.services.prompt_generation_service import PromptGenerationService
from app.services.state_service import StateService


def test_offline_mvp_flow_generates_chapter_specific_prompts_with_evidence(pg_session: Session) -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "tiny_novel.md"
    manifest = ImportService().parse_path(fixture_path, title="Tiny Novel", author="Test Author")
    novel_repository = NovelRepository(pg_session)
    novel = novel_repository.create_from_manifest(manifest, source_path=str(fixture_path))
    pg_session.commit()

    chunk_repository = ChunkRepository(pg_session)
    chunker = ChunkingService()
    chapters = novel_repository.list_chapters(novel.id)
    for chapter in chapters:
        chunk_repository.replace_chunks_for_chapter(
            novel_id=novel.id,
            chapter_id=chapter.id,
            chapter_index=chapter.chapter_index,
            chunks=chunker.chunk_chapter(chapter.content),
        )
    EmbeddingService(chunk_repository, FakeEmbeddingProvider()).embed_missing_chunks(novel.id)
    pg_session.commit()

    chunks = chunk_repository.list_chunks_for_chapter(chapters[0].id)
    character_service = CharacterService(CharacterRepository(pg_session))
    character = character_service.create_character_candidate(
        novel_id=novel.id,
        canonical_name="林青",
        source_chunk_ids=[str(chunks[0].id)],
        confidence=0.95,
    )
    character_service.confirm_character(character.id, reviewer="test", note="fixture character")

    state_service = StateService(StateRepository(pg_session))
    initial_state = state_service.create_initial_state_candidate(
        novel_id=novel.id,
        character_id=character.id,
        chapter_start=1,
        source_chunk_ids=[str(chunks[0].id)],
        fields=CharacterStateFields(
            appearance="wearing a plain blue cloth robe and carrying an old sword",
            personality="quiet and disciplined",
            identity="outer disciple",
            motivation="prove he can stay in the sect",
            relationship_summary="newcomer with no stable allies yet",
            visual_keywords=["blue cloth robe", "old sword", "quiet gaze"],
            negative_prompt="modern clothing",
        ),
        confidence=0.9,
    )
    state_service.confirm_state(initial_state.id, reviewer="test", note="initial fixture state")

    chapter_two = chapters[1]
    chapter_two_chunks = chunk_repository.list_chunks_for_chapter(chapter_two.id)
    event = CharacterEvent(
        novel_id=novel.id,
        character_id=character.id,
        chapter_id=chapter_two.id,
        chapter_index=2,
        event_summary="林青通过试炼，从外门弟子升为内门弟子。",
        event_type=EventType.IDENTITY.value,
        is_long_term_change=True,
        affected_fields=["identity", "appearance", "visual_keywords", "motivation"],
        source_chunk_ids=[str(chapter_two_chunks[0].id)],
        confidence=0.92,
        explanation="第二章明确描述身份和服装变化。",
        status=ReviewStatus.CONFIRMED.value,
    )
    pg_session.add(event)
    pg_session.flush()
    state_change = CharacterStateChange(
        novel_id=novel.id,
        character_id=character.id,
        event_id=event.id,
        chapter_id=chapter_two.id,
        chapter_index=2,
        changed_fields=[
            {
                "field": "identity",
                "before": "outer disciple",
                "after": "inner disciple",
                "source_chunk_ids": [str(chapter_two_chunks[0].id)],
            },
            {
                "field": "appearance",
                "before": "wearing a plain blue cloth robe and carrying an old sword",
                "after": "wearing a green inner-sect robe and carrying a new sword",
                "source_chunk_ids": [str(chapter_two_chunks[0].id)],
            },
            {
                "field": "visual_keywords",
                "before": ["blue cloth robe", "old sword", "quiet gaze"],
                "after": ["green inner-sect robe", "new sword", "determined gaze"],
                "source_chunk_ids": [str(chapter_two_chunks[0].id)],
            },
            {
                "field": "motivation",
                "before": "prove he can stay in the sect",
                "after": "protect the sect as an inner disciple",
                "source_chunk_ids": [str(chapter_two_chunks[0].id)],
            },
        ],
        source_chunk_ids=[str(chapter_two_chunks[0].id)],
        confidence=0.91,
        explanation="身份、服装和动机都发生长期变化。",
        status=ReviewStatus.CONFIRMED.value,
    )
    pg_session.add(state_change)
    pg_session.flush()
    new_state = state_service.synthesize_candidate_from_change(state_change.id)
    state_service.confirm_state(new_state.id, reviewer="test", note="identity change fixture state")
    pg_session.commit()

    prompt_service = PromptGenerationService(
        state_repository=StateRepository(pg_session),
        chunk_repository=chunk_repository,
        prompt_repository=PromptRepository(pg_session),
        evidence_service=EvidenceService(
            state_repository=StateRepository(pg_session),
            chunk_repository=chunk_repository,
        ),
    )
    chapter_one_prompt = prompt_service.generate_character_prompt(
        novel_id=novel.id,
        chapter_index=1,
        character_id=character.id,
    )
    chapter_three_prompt = prompt_service.generate_character_prompt(
        novel_id=novel.id,
        chapter_index=3,
        character_id=character.id,
    )

    assert chapter_one_prompt.character_state_id == initial_state.id
    assert chapter_three_prompt.character_state_id == new_state.id
    assert "outer disciple" in chapter_one_prompt.final_prompt
    assert "inner disciple" in chapter_three_prompt.final_prompt
    assert "blue cloth robe" in chapter_one_prompt.final_prompt
    assert "green inner-sect robe" in chapter_three_prompt.final_prompt
    assert chapter_three_prompt.used_event_ids == [str(event.id)]
    assert chapter_three_prompt.used_chunk_ids
    assert chapter_three_prompt.evidence_snapshot["state"]["id"] == str(new_state.id)
    assert chapter_three_prompt.evidence_snapshot["events"][0]["id"] == str(event.id)
    assert chapter_three_prompt.evidence_snapshot["chunks"]

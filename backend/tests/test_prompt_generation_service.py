from datetime import UTC, datetime
import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.enums import PromptType, ReviewStatus
from app.models.character import Character
from app.models.novel import Chapter, ChapterChunk, Novel
from app.models.state import CharacterEvent, CharacterState
from app.repositories.chunks import ChunkRepository
from app.repositories.prompts import PromptRepository
from app.repositories.states import StateRepository
from app.services.evidence_service import EvidenceService
from app.services.prompt_generation_service import PromptGenerationService


def test_evidence_service_returns_serializable_state_event_and_chunk_bundle(pg_session: Session) -> None:
    fixture = _create_prompt_fixture(pg_session)
    service = EvidenceService(
        state_repository=StateRepository(pg_session),
        chunk_repository=ChunkRepository(pg_session),
    )

    bundle = service.build_bundle(
        state_id=fixture.confirmed_state.id,
        event_ids=[fixture.confirmed_event.id],
        chunk_ids=[fixture.chunk.id],
    )

    assert bundle["state"]["id"] == str(fixture.confirmed_state.id)
    assert bundle["state"]["identity"] == "inner disciple"
    assert bundle["events"][0]["id"] == str(fixture.confirmed_event.id)
    assert bundle["events"][0]["event_summary"] == "Lin Qing entered the inner sect."
    assert bundle["chunks"][0]["id"] == str(fixture.chunk.id)
    assert bundle["chunks"][0]["chapter_index"] == 3
    assert bundle["chunks"][0]["text"] == fixture.chunk.text


def test_evidence_service_fails_when_requested_event_id_is_missing(pg_session: Session) -> None:
    fixture = _create_prompt_fixture(pg_session)
    service = EvidenceService(
        state_repository=StateRepository(pg_session),
        chunk_repository=ChunkRepository(pg_session),
    )

    with pytest.raises(ValueError, match="Event evidence not found"):
        service.build_bundle(
            state_id=fixture.confirmed_state.id,
            event_ids=[uuid.uuid4()],
            chunk_ids=[fixture.chunk.id],
        )


def test_evidence_service_fails_when_requested_chunk_id_is_missing(pg_session: Session) -> None:
    fixture = _create_prompt_fixture(pg_session)
    service = EvidenceService(
        state_repository=StateRepository(pg_session),
        chunk_repository=ChunkRepository(pg_session),
    )

    with pytest.raises(ValueError, match="Chunk evidence not found"):
        service.build_bundle(
            state_id=fixture.confirmed_state.id,
            event_ids=[fixture.confirmed_event.id],
            chunk_ids=[uuid.uuid4()],
        )


def test_prompt_generation_uses_confirmed_state_chunks_and_confirmed_events(pg_session: Session) -> None:
    fixture = _create_prompt_fixture(pg_session)
    service = _prompt_service(pg_session)

    record = service.generate_character_prompt(
        novel_id=fixture.novel.id,
        chapter_index=3,
        character_id=fixture.character.id,
        user_request="portrait for chapter 3",
    )

    assert record.prompt_type == PromptType.CHARACTER.value
    assert record.character_state_id == fixture.confirmed_state.id
    assert record.used_chunk_ids == [str(fixture.chunk.id)]
    assert record.used_event_ids == [str(fixture.confirmed_event.id)]
    assert "inner disciple" in record.final_prompt
    assert "green robe" in record.final_prompt
    assert "moonlit training yard" in record.final_prompt
    assert record.evidence_snapshot["state"]["id"] == str(fixture.confirmed_state.id)


def test_prompt_generation_builds_concise_visual_prompt_without_author_notes(pg_session: Session) -> None:
    chunk_text = (
        "塔莉亚站在地下圣殿遗迹中央，身旁的淡蓝晶体亮起冷光。"
        "她握紧长柄锤矛，黑甲边缘映出苍白火焰。\n"
        "新人新书，求收藏追读，谢谢大家支持。\n"
        "后续还有很多设定会慢慢展开。"
    )
    fixture = _create_prompt_fixture(
        pg_session,
        state_appearance="瘦高身形，钢灰色头发，钢灰色眼睛，苍白脸色，黑眼圈明显。身覆狰狞黑甲，披着猩红披风。",
        chunk_text=chunk_text,
    )
    fixture.character.canonical_name = "塔莉亚·罗诺威"
    fixture.confirmed_state.identity = "塔莉亚·罗诺威，混血魔族，隆多兰地下城继承者。"
    fixture.confirmed_state.personality = "疲惫但执拗，敢赌，带一点自嘲。"
    fixture.confirmed_state.motivation = "用淡蓝晶体激活地下遗迹，寻找最后一次翻身机会。"
    fixture.confirmed_state.relationship_summary = "父亲曾是隆多兰地下城的魔国君王。"
    fixture.confirmed_state.visual_keywords = ["钢灰色头发", "黑甲", "猩红披风", "淡蓝晶体", "地下圣殿"]
    pg_session.commit()
    service = _prompt_service(pg_session)

    record = service.generate_character_prompt(
        novel_id=fixture.novel.id,
        chapter_index=3,
        character_id=fixture.character.id,
        user_request="强调地下遗迹中的孤独感",
    )

    assert "钢灰色头发" in record.final_prompt
    assert "黑甲" in record.final_prompt
    assert "猩红披风" in record.final_prompt
    assert "淡蓝晶体" in record.final_prompt
    assert "地下圣殿" in record.final_prompt
    assert "强调地下遗迹中的孤独感" in record.final_prompt
    assert "新人新书" not in record.final_prompt
    assert "求收藏追读" not in record.final_prompt
    assert chunk_text not in record.final_prompt
    assert record.evidence_snapshot["chunks"][0]["text"] == chunk_text
    assert record.negative_prompt == "modern clothing"


def test_prompt_generation_summarizes_scene_slots_instead_of_copying_long_prose(pg_session: Session) -> None:
    chunk_text = (
        "轰隆——地下遗迹深处的石门缓慢开启，尘埃从穹顶落下。\n"
        "“这是哪儿啊？”她低声问，回声在空旷殿堂里反复震荡。\n"
        "塔莉亚站在地下遗迹中央，黑甲映着苍白火焰，猩红披风被冷风卷起。"
        "她掌心的淡蓝晶体闪烁，照亮脚下破碎的石阶。\n"
        "新人新书，求收藏追读。\n"
        "本章完。"
    )
    fixture = _create_prompt_fixture(
        pg_session,
        state_appearance="瘦高身形，钢灰色头发，身覆狰狞黑甲，披着猩红披风。",
        chunk_text=chunk_text,
    )
    fixture.character.canonical_name = "塔莉亚·罗诺威"
    fixture.confirmed_state.identity = "塔莉亚·罗诺威，混血魔族。"
    fixture.confirmed_state.personality = "疲惫、执拗、孤注一掷。"
    fixture.confirmed_state.motivation = "寻找地下遗迹中的最后机会。"
    fixture.confirmed_state.visual_keywords = ["黑甲", "猩红披风", "淡蓝晶体", "地下遗迹"]
    pg_session.commit()
    service = _prompt_service(pg_session)

    record = service.generate_character_prompt(
        novel_id=fixture.novel.id,
        chapter_index=3,
        character_id=fixture.character.id,
    )

    assert "location:" in record.final_prompt
    assert "lighting:" in record.final_prompt
    assert "character_pose:" in record.final_prompt
    assert "important_props:" in record.final_prompt
    assert "黑甲" in record.final_prompt
    assert "猩红披风" in record.final_prompt
    assert "淡蓝晶体" in record.final_prompt
    assert "地下遗迹" in record.final_prompt
    assert "轰隆——" not in record.final_prompt
    assert "这是哪儿啊" not in record.final_prompt
    assert "新人新书" not in record.final_prompt
    assert "求收藏追读" not in record.final_prompt
    assert "本章完" not in record.final_prompt
    assert record.evidence_snapshot["chunks"][0]["text"] == chunk_text


def test_prompt_generation_scene_summary_is_not_hardcoded_to_first_chapter(pg_session: Session) -> None:
    chunk_text = (
        "雨夜城墙上，守卫举着油灯巡逻，湿冷的石砖反射出昏黄光晕。"
        "女骑士披着深蓝斗篷，单膝跪在箭垛旁检查银色长弓。"
        "远处森林被雾气吞没，破旗在风中发出低响。"
    )
    fixture = _create_prompt_fixture(
        pg_session,
        state_appearance="女骑士，深蓝斗篷，银色长弓，皮甲上沾着雨水。",
        chunk_text=chunk_text,
    )
    fixture.character.canonical_name = "艾琳"
    fixture.confirmed_state.identity = "边境守夜骑士。"
    fixture.confirmed_state.personality = "冷静、警觉。"
    fixture.confirmed_state.motivation = "守住雨夜中的城墙。"
    fixture.confirmed_state.visual_keywords = ["深蓝斗篷", "银色长弓", "雨夜城墙", "油灯"]
    pg_session.commit()
    service = _prompt_service(pg_session)

    record = service.generate_character_prompt(
        novel_id=fixture.novel.id,
        chapter_index=3,
        character_id=fixture.character.id,
    )

    assert "雨夜城墙" in record.final_prompt
    assert "油灯" in record.final_prompt
    assert "深蓝斗篷" in record.final_prompt
    assert "银色长弓" in record.final_prompt
    assert "location:" in record.final_prompt
    assert "地下圣殿" not in record.final_prompt
    assert "淡蓝晶体" not in record.final_prompt
    assert "法阵" not in record.final_prompt


def test_prompt_generation_fails_without_covering_confirmed_state(pg_session: Session) -> None:
    fixture = _create_prompt_fixture(pg_session, state_status=ReviewStatus.REJECTED.value)
    service = _prompt_service(pg_session)

    with pytest.raises(ValueError, match="No confirmed CharacterState"):
        service.generate_character_prompt(
            novel_id=fixture.novel.id,
            chapter_index=3,
            character_id=fixture.character.id,
        )


def test_prompt_generation_fails_with_candidate_state_only(pg_session: Session) -> None:
    fixture = _create_prompt_fixture(pg_session, state_status=ReviewStatus.CANDIDATE.value)
    service = _prompt_service(pg_session)

    with pytest.raises(ValueError, match="No confirmed CharacterState"):
        service.generate_character_prompt(
            novel_id=fixture.novel.id,
            chapter_index=3,
            character_id=fixture.character.id,
        )


def test_prompt_generation_saves_warning_for_current_scene_clothing_conflict(pg_session: Session) -> None:
    fixture = _create_prompt_fixture(
        pg_session,
        state_appearance="young swordsman wearing a plain gray robe",
        chunk_text="Lin Qing stands in the moonlit training yard, wearing a red ceremonial robe.",
    )
    service = _prompt_service(pg_session)

    record = service.generate_character_prompt(
        novel_id=fixture.novel.id,
        chapter_index=3,
        character_id=fixture.character.id,
    )

    assert record.warnings == [
        {
            "type": "state_chunk_conflict",
            "field": "clothing",
            "state_value": "young swordsman wearing a plain gray robe",
            "chunk_value": fixture.chunk.text,
            "resolution": "used explicit current-scene chunk value",
        }
    ]
    assert "red ceremonial robe" in record.final_prompt


def test_prompt_generation_ignores_candidate_events(pg_session: Session) -> None:
    fixture = _create_prompt_fixture(pg_session, event_status=ReviewStatus.CANDIDATE.value)
    service = _prompt_service(pg_session)

    record = service.generate_character_prompt(
        novel_id=fixture.novel.id,
        chapter_index=3,
        character_id=fixture.character.id,
    )

    assert record.used_event_ids == []
    assert record.evidence_snapshot["events"] == []


def test_prompt_generation_rejects_character_state_from_different_novel(pg_session: Session) -> None:
    first = _create_prompt_fixture(pg_session)
    second = _create_prompt_fixture(pg_session)
    service = _prompt_service(pg_session)

    with pytest.raises(ValueError, match="No confirmed CharacterState"):
        service.generate_character_prompt(
            novel_id=first.novel.id,
            chapter_index=3,
            character_id=second.character.id,
        )


class PromptFixture:
    def __init__(
        self,
        *,
        novel: Novel,
        chapter: Chapter,
        chunk: ChapterChunk,
        character: Character,
        confirmed_state: CharacterState,
        confirmed_event: CharacterEvent,
    ) -> None:
        self.novel = novel
        self.chapter = chapter
        self.chunk = chunk
        self.character = character
        self.confirmed_state = confirmed_state
        self.confirmed_event = confirmed_event


def _prompt_service(pg_session: Session) -> PromptGenerationService:
    state_repository = StateRepository(pg_session)
    chunk_repository = ChunkRepository(pg_session)
    return PromptGenerationService(
        state_repository=state_repository,
        chunk_repository=chunk_repository,
        prompt_repository=PromptRepository(pg_session),
        evidence_service=EvidenceService(
            state_repository=state_repository,
            chunk_repository=chunk_repository,
        ),
    )


def _create_prompt_fixture(
    pg_session: Session,
    *,
    state_status: str = ReviewStatus.CONFIRMED.value,
    event_status: str = ReviewStatus.CONFIRMED.value,
    state_appearance: str = "young swordsman wearing a green robe",
    chunk_text: str = "Lin Qing stands in the moonlit training yard.",
) -> PromptFixture:
    novel = Novel(
        title="Prompt Novel",
        source_type="markdown",
        language="zh",
        meta={},
        imported_at=datetime.now(UTC),
    )
    pg_session.add(novel)
    pg_session.flush()
    chapter = Chapter(
        novel_id=novel.id,
        chapter_index=3,
        title="Chapter 3",
        content=chunk_text,
        summary="Lin Qing trains at night.",
        word_count=8,
        checksum="prompt-chapter-3",
    )
    character = Character(
        novel_id=novel.id,
        canonical_name="Lin Qing",
        status=ReviewStatus.CONFIRMED.value,
        source_chunk_ids=[],
    )
    pg_session.add_all([chapter, character])
    pg_session.flush()
    chunk = ChapterChunk(
        novel_id=novel.id,
        chapter_id=chapter.id,
        chapter_index=3,
        chunk_index=1,
        text=chunk_text,
        start_char=0,
        end_char=len(chunk_text),
        char_count=len(chunk_text),
        token_count=len(chunk_text),
        checksum="prompt-chunk-3-1",
        meta={},
    )
    state = CharacterState(
        novel_id=novel.id,
        character_id=character.id,
        chapter_start=1,
        chapter_end=None,
        appearance=state_appearance,
        personality="disciplined and quiet",
        identity="inner disciple",
        motivation="prove himself",
        relationship_summary="trusted by his mentor",
        visual_keywords=["green robe", "sword", "calm gaze"],
        negative_prompt="modern clothing",
        source_chapters=[1, 3],
        source_chunk_ids=[str(chunk.id)],
        confidence=0.9,
        status=state_status,
    )
    event = CharacterEvent(
        novel_id=novel.id,
        character_id=character.id,
        chapter_id=chapter.id,
        chapter_index=2,
        event_summary="Lin Qing entered the inner sect.",
        event_type="identity",
        is_long_term_change=True,
        affected_fields=["identity"],
        source_chunk_ids=[str(chunk.id)],
        confidence=0.88,
        explanation="The sect accepted him as an inner disciple.",
        status=event_status,
    )
    pg_session.add_all([chunk, state, event])
    pg_session.commit()
    return PromptFixture(
        novel=novel,
        chapter=chapter,
        chunk=chunk,
        character=character,
        confirmed_state=state,
        confirmed_event=event,
    )

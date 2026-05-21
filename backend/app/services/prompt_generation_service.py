import re
import uuid

from app.core.enums import PromptType
from app.models.novel import ChapterChunk
from app.models.prompt import PromptGeneration
from app.models.state import CharacterEvent, CharacterState
from app.repositories.chunks import ChunkRepository
from app.repositories.prompts import PromptRepository
from app.repositories.states import StateRepository
from app.services.evidence_service import EvidenceService


SCENE_EXCERPT_CHAR_LIMIT = 360
EVENT_CONTEXT_CHAR_LIMIT = 220
SCENE_SLOT_CHAR_LIMIT = 120
NON_VISUAL_TEXT_MARKERS = (
    "新人新书",
    "求收藏",
    "求追读",
    "收藏追读",
    "谢谢大家",
    "作者",
    "本章未完",
    "本章完",
    "点击下一页",
    "上一章",
    "下一章",
    "这是哪儿啊",
    "同学",
    "cosplay",
)
VISUAL_SENTENCE_KEYWORDS = (
    "站",
    "跪",
    "坐",
    "走",
    "握",
    "举",
    "披",
    "检查",
    "光",
    "亮",
    "火",
    "灯",
    "夜",
    "雨",
    "雾",
    "风",
    "影",
    "墙",
    "殿",
    "厅",
    "城",
    "森林",
    "遗迹",
    "石",
    "门",
    "甲",
    "披风",
    "斗篷",
    "剑",
    "弓",
    "锤",
    "矛",
    "晶体",
)
LOCATION_KEYWORDS = ("遗迹", "圣殿", "殿堂", "城墙", "森林", "宴会厅", "沙漠", "营地", "房间", "石门", "庭院", "街道")
LIGHTING_KEYWORDS = ("光", "亮", "火", "灯", "月", "夜", "闪烁", "发光", "光晕", "阴影", "色调")
POSE_KEYWORDS = ("站", "跪", "坐", "走", "握", "举", "披", "检查", "注视", "奔", "靠")
PROP_KEYWORDS = ("晶体", "剑", "弓", "锤", "矛", "法杖", "钥匙", "油灯", "旗", "石门", "武器", "道具")
ENVIRONMENT_KEYWORDS = ("石", "墙", "雨", "雾", "风", "尘埃", "森林", "城", "殿", "阶", "背景", "远处")


class PromptGenerationService:
    def __init__(
        self,
        *,
        state_repository: StateRepository,
        chunk_repository: ChunkRepository,
        prompt_repository: PromptRepository,
        evidence_service: EvidenceService,
    ) -> None:
        self.state_repository = state_repository
        self.chunk_repository = chunk_repository
        self.prompt_repository = prompt_repository
        self.evidence_service = evidence_service

    def generate_character_prompt(
        self,
        *,
        novel_id: uuid.UUID,
        chapter_index: int,
        character_id: uuid.UUID,
        user_request: str | None = None,
        model_provider: str = "fake",
        model_name: str = "prompt-template-v1",
        model_params: dict | None = None,
    ) -> PromptGeneration:
        chapter = self.chunk_repository.get_chapter_by_index(novel_id, chapter_index)
        if chapter is None:
            raise ValueError(f"Chapter not found for novel {novel_id} at index {chapter_index}")
        state = self._confirmed_state_for_chapter(novel_id, character_id, chapter_index)
        chunks = self.chunk_repository.list_chunks_for_chapter_window(
            novel_id=novel_id,
            chapter_index=chapter_index,
            window=0,
        )
        events = self.state_repository.recent_confirmed_events(
            character_id=character_id,
            chapter_index=chapter_index,
            limit=5,
        )
        warnings = self._detect_conflict_warnings(state, chunks)
        final_prompt = self._build_prompt(state=state, chunks=chunks, events=events, user_request=user_request)
        event_ids = [event.id for event in events]
        chunk_ids = [chunk.id for chunk in chunks]
        evidence_snapshot = self.evidence_service.build_bundle(
            state_id=state.id,
            event_ids=event_ids,
            chunk_ids=chunk_ids,
        )
        prompt_generation = PromptGeneration(
            novel_id=novel_id,
            chapter_id=chapter.id,
            chapter_index=chapter_index,
            character_id=character_id,
            character_state_id=state.id,
            prompt_type=PromptType.CHARACTER.value,
            user_request=user_request,
            final_prompt=final_prompt,
            negative_prompt=state.negative_prompt,
            model_provider=model_provider,
            model_name=model_name,
            model_params=model_params or {},
            used_event_ids=[str(event_id) for event_id in event_ids],
            used_chunk_ids=[str(chunk_id) for chunk_id in chunk_ids],
            warnings=warnings,
            evidence_snapshot=evidence_snapshot,
        )
        return self.prompt_repository.add_prompt_generation(prompt_generation)

    def _confirmed_state_for_chapter(
        self,
        novel_id: uuid.UUID,
        character_id: uuid.UUID,
        chapter_index: int,
    ) -> CharacterState:
        states = self.state_repository.confirmed_states_covering(
            novel_id=novel_id,
            character_id=character_id,
            chapter_index=chapter_index,
        )
        if not states:
            raise ValueError("No confirmed CharacterState covers the requested chapter")
        if len(states) > 1:
            raise ValueError("Multiple confirmed CharacterState records cover the requested chapter")
        return states[0]

    def _build_prompt(
        self,
        *,
        state: CharacterState,
        chunks: list[ChapterChunk],
        events: list[CharacterEvent],
        user_request: str | None,
    ) -> str:
        scene_summary = self._visual_scene_summary(chunks, state)
        event_context = self._event_context(events)
        parts = [
            f"A full-body dark fantasy character portrait of {state.identity or 'the character'}.",
            f"Appearance and equipment: {state.appearance or 'unknown'}.",
            f"Core visual keywords: {', '.join(state.visual_keywords) if state.visual_keywords else 'none'}.",
            f"Personality and mood: {state.personality or 'unknown'}.",
            f"Motivation/emotional direction: {state.motivation or 'unknown'}.",
        ]
        if scene_summary:
            parts.append(scene_summary)
        if event_context:
            parts.append(f"Recent story context for continuity: {event_context}.")
        if user_request:
            parts.append(f"User request to incorporate: {user_request}.")
        parts.append(
            "Style: cinematic dark fantasy, detailed armor and fabric, cold magical glow, "
            "dramatic lighting, vertical composition, sharp character focus, high-detail illustration."
        )
        return "\n".join(parts)

    def _visual_scene_summary(self, chunks: list[ChapterChunk], state: CharacterState) -> str:
        sentences = self._visual_sentences(chunks)
        location = self._slot_terms(sentences, LOCATION_KEYWORDS)
        lighting = self._slot_terms(sentences, LIGHTING_KEYWORDS)
        character_pose = self._slot_terms(sentences, POSE_KEYWORDS)
        important_props = self._slot_terms(sentences, PROP_KEYWORDS)
        environment_details = self._slot_terms(sentences, ENVIRONMENT_KEYWORDS)
        fallback = self._visual_scene_excerpt(chunks, limit=SCENE_SLOT_CHAR_LIMIT)

        slot_values = {
            "location": location or fallback or "current chapter setting",
            "lighting": lighting or "use lighting implied by the current scene",
            "character_pose": character_pose or "pose the character according to the requested moment",
            "clothing_and_equipment": self._state_visual_anchor(state),
            "important_props": self._merge_terms(important_props, self._keywords_text(state.visual_keywords[-4:])),
            "environment_details": environment_details or fallback or "background details from the current chapter",
            "mood": self._shorten(" ".join(item for item in [state.personality, state.motivation] if item), SCENE_SLOT_CHAR_LIMIT)
            or "story-appropriate mood",
            "composition": "full-body vertical composition, character in sharp focus, environment visible behind them",
        }
        return "Visual scene summary:\n" + "\n".join(f"- {slot}: {value}" for slot, value in slot_values.items())

    def _visual_sentences(self, chunks: list[ChapterChunk]) -> list[str]:
        sentences: list[str] = []
        for chunk in chunks:
            text = chunk.text.replace("\r\n", "\n").replace("\n", " ")
            for sentence in re.split(r"(?<=[。！？.!?])\s*", text):
                cleaned = sentence.strip()
                if not cleaned or self._is_non_visual_sentence(cleaned):
                    continue
                if not any(keyword in cleaned for keyword in VISUAL_SENTENCE_KEYWORDS):
                    continue
                sentences.append(self._shorten(cleaned, SCENE_SLOT_CHAR_LIMIT))
        return sentences

    def _is_non_visual_sentence(self, sentence: str) -> bool:
        if any(marker in sentence for marker in NON_VISUAL_TEXT_MARKERS):
            return True
        return any(marker in sentence for marker in ("“", "”", '"', "——"))

    def _first_matching_sentence(self, sentences: list[str], keywords: tuple[str, ...]) -> str:
        for sentence in sentences:
            if any(keyword in sentence for keyword in keywords):
                return sentence
        return ""

    def _slot_terms(self, sentences: list[str], keywords: tuple[str, ...]) -> str:
        terms: list[str] = []
        for sentence in sentences:
            for keyword in keywords:
                if keyword in sentence and keyword not in terms:
                    terms.append(keyword)
            if len(terms) >= 6:
                break
        return ", ".join(terms)

    def _merge_terms(self, primary: str, secondary: str) -> str:
        terms: list[str] = []
        for text in [primary, secondary]:
            for term in [item.strip() for item in text.split(",") if item.strip()]:
                if term not in terms:
                    terms.append(term)
        return ", ".join(terms)

    def _state_visual_anchor(self, state: CharacterState) -> str:
        if state.visual_keywords:
            return self._shorten(self._keywords_text(state.visual_keywords), SCENE_SLOT_CHAR_LIMIT)
        return self._shorten(state.appearance or "", SCENE_SLOT_CHAR_LIMIT) or "state-defined outfit and equipment"

    def _keywords_text(self, keywords: list[str]) -> str:
        return ", ".join(keywords)

    def _shorten(self, text: str, limit: int) -> str:
        compact = " ".join(text.split())
        if len(compact) <= limit:
            return compact
        return compact[:limit].rstrip(" ，。,.") + "..."

    def _visual_scene_excerpt(self, chunks: list[ChapterChunk], limit: int = SCENE_EXCERPT_CHAR_LIMIT) -> str:
        lines: list[str] = []
        for chunk in chunks:
            for raw_line in chunk.text.replace("\r\n", "\n").split("\n"):
                line = raw_line.strip()
                if not line or self._is_non_visual_sentence(line):
                    continue
                lines.append(line)
        excerpt = " ".join(lines)
        return self._shorten(excerpt, limit)

    def _event_context(self, events: list[CharacterEvent]) -> str:
        text = " ".join(event.event_summary.strip() for event in events if event.event_summary.strip())
        if len(text) <= EVENT_CONTEXT_CHAR_LIMIT:
            return text
        return text[:EVENT_CONTEXT_CHAR_LIMIT].rstrip(" ，。,.") + "..."

    def _detect_conflict_warnings(self, state: CharacterState, chunks: list[ChapterChunk]) -> list[dict]:
        if not state.appearance or "robe" not in state.appearance.lower():
            return []
        warnings: list[dict] = []
        state_appearance = state.appearance.lower()
        for chunk in chunks:
            chunk_text = chunk.text.lower()
            if "robe" in chunk_text and "red" in chunk_text and "red" not in state_appearance:
                warnings.append(
                    {
                        "type": "state_chunk_conflict",
                        "field": "clothing",
                        "state_value": state.appearance,
                        "chunk_value": chunk.text,
                        "resolution": "used explicit current-scene chunk value",
                    }
                )
        return warnings

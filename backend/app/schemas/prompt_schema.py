from pydantic import BaseModel


class EvidenceState(BaseModel):
    id: str
    character_id: str
    chapter_start: int
    chapter_end: int | None
    appearance: str | None
    personality: str | None
    identity: str | None
    motivation: str | None
    relationship_summary: str | None
    visual_keywords: list[str]
    negative_prompt: str | None
    source_chapters: list[int]
    source_chunk_ids: list[str]
    confidence: float | None


class EvidenceEvent(BaseModel):
    id: str
    character_id: str | None
    chapter_index: int
    event_summary: str
    event_type: str
    affected_fields: list[str]
    source_chunk_ids: list[str]
    confidence: float | None
    explanation: str | None


class EvidenceChunk(BaseModel):
    id: str
    chapter_id: str
    chapter_index: int
    chunk_index: int
    text: str
    start_char: int
    end_char: int
    checksum: str


class EvidenceBundle(BaseModel):
    state: EvidenceState | None
    events: list[EvidenceEvent]
    chunks: list[EvidenceChunk]

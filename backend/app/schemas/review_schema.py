from pydantic import BaseModel, Field


class CharacterStateFields(BaseModel):
    appearance: str | None = None
    personality: str | None = None
    identity: str | None = None
    motivation: str | None = None
    relationship_summary: str | None = None
    visual_keywords: list[str] = Field(default_factory=list)
    negative_prompt: str | None = None

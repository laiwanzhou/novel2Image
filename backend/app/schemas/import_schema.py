from typing import Literal

from pydantic import BaseModel, Field


class ChapterInput(BaseModel):
    chapter_index: int
    title: str
    content: str
    source_path: str | None = None
    word_count: int
    checksum: str


class BookManifest(BaseModel):
    title: str
    author: str | None = None
    source_type: Literal["txt", "markdown", "epub", "manifest"]
    language: str = "zh"
    chapters: list[ChapterInput] = Field(default_factory=list)

"""SQLAlchemy model package.

Importing this module registers all model classes on Base.metadata for Alembic.
"""

from app.models.base import Base
from app.models.character import Character, CharacterAlias
from app.models.novel import Chapter, ChapterChunk, Novel
from app.models.prompt import GeneratedImage, PromptGeneration, ReviewAction
from app.models.state import CharacterEvent, CharacterState, CharacterStateChange

__all__ = [
    "Base",
    "Chapter",
    "ChapterChunk",
    "Character",
    "CharacterAlias",
    "CharacterEvent",
    "CharacterState",
    "CharacterStateChange",
    "GeneratedImage",
    "Novel",
    "PromptGeneration",
    "ReviewAction",
]

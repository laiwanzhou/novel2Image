import uuid

from sqlalchemy import func, select

from app.models.prompt import PromptGeneration
from app.repositories.base import BaseRepository


class PromptRepository(BaseRepository[PromptGeneration]):
    def add_prompt_generation(self, prompt_generation: PromptGeneration) -> PromptGeneration:
        self.session.add(prompt_generation)
        self.session.flush()
        return prompt_generation

    def get_prompt_generation(self, prompt_generation_id: uuid.UUID) -> PromptGeneration | None:
        return self.session.get(PromptGeneration, prompt_generation_id)

    def list_prompt_generations(self, novel_id: uuid.UUID) -> list[PromptGeneration]:
        statement = (
            select(PromptGeneration)
            .where(PromptGeneration.novel_id == novel_id)
            .order_by(PromptGeneration.created_at, PromptGeneration.id)
        )
        return list(self.session.scalars(statement))

    def count_prompt_generations(self, novel_id: uuid.UUID) -> int:
        statement = select(func.count()).select_from(PromptGeneration).where(PromptGeneration.novel_id == novel_id)
        return int(self.session.scalar(statement) or 0)

    def has_prompt_generations(self, novel_id: uuid.UUID) -> bool:
        statement = select(PromptGeneration.id).where(PromptGeneration.novel_id == novel_id).limit(1)
        return self.session.scalar(statement) is not None

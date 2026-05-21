from typing import Generic, TypeVar

from sqlalchemy.orm import Session


ModelT = TypeVar("ModelT")


class BaseRepository(Generic[ModelT]):
    """Small repository base that keeps database access behind repositories."""

    def __init__(self, session: Session) -> None:
        self.session = session

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings
from app.core.enums import PromptType
from app.models.base import Base
from app.repositories.base import BaseRepository


def test_settings_have_required_provider_names() -> None:
    settings = Settings()

    assert settings.embedding_provider == "fake"
    assert settings.llm_provider == "fake"


def test_prompt_type_excludes_group_for_mvp() -> None:
    assert {item.value for item in PromptType} == {"character", "scene"}


def test_health_endpoint() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_foundation_imports() -> None:
    assert Base.metadata is not None
    assert BaseRepository is not None

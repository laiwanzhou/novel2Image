from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/novel_visualization"
    test_database_url: str = "postgresql+psycopg://postgres:postgres@localhost:55432/novel_visualization_test"
    embedding_provider: str = "fake"
    llm_provider: str = "fake"
    llm_api_base: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_json_mode: bool = True
    llm_max_tokens: int = 4096
    llm_timeout_seconds: float = 180.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="NOVEL_VIS_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

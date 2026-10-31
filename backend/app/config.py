from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV, extra="ignore")

    null_env: str = "development"
    null_database_url: str = "postgresql+psycopg://localhost/null_app"
    null_secret_key: str = ""
    null_cors_origins: str = "http://localhost:3000"
    null_session_hours: int = 12
    null_demo_password: str = ""

    model_api_key: str = ""
    meta_api_base: str = "https://api.meta.ai/v1"
    meta_model_id: str = ""
    meta_reasoning_effort: str = "medium"
    null_allow_contributor_models: bool = False

    @field_validator("meta_api_base")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def is_production(self) -> bool:
        return self.null_env == "production"

    @property
    def secret_key(self) -> str:
        if self.null_secret_key:
            return self.null_secret_key
        if self.is_production:
            raise RuntimeError("NULL_SECRET_KEY must be set in production")
        return "local-development-only-secret-not-for-production-use"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.null_cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

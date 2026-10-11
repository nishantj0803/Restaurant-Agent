from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.5-flash-lite"
    tavily_api_key: SecretStr = SecretStr("")
    request_timeout_seconds: int = Field(default=240, ge=30, le=600)

    @property
    def missing_keys(self) -> list[str]:
        return [
            name
            for name, value in (
                ("GEMINI_API_KEY", self.gemini_api_key),
                ("TAVILY_API_KEY", self.tavily_api_key),
            )
            if not value.get_secret_value()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Legal Checker API"
    app_version: str = "0.1.0"
    ner_model_name: str = ""
    ner_device: int = -1
    ner_min_score: float = 0.6

    model_config = SettingsConfigDict(env_file=".env", env_prefix="LEGAL_", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()

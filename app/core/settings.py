from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Legal Checker API"
    app_version: str = "0.1.0"
    ner_model_name: str = ""
    ner_device: int = -1
    ner_min_score: float = 0.6
    llm_provider: str = "openrouter"
    llm_model: str = "openai/gpt-4o-mini"
    llm_timeout_sec: int = 20
    llm_max_retries: int = 2
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_http_referer: str = ""
    openrouter_title: str = "Legal Checker API"
    vllm_base_url: str = "http://localhost:8000/v1"
    vllm_api_key: str = "local-token"
    vllm_model: str = "local-model"
    retriever_timeout_sec: int = 8
    retriever_top_k: int = 3
    allowed_source_domains: str = "pravo.gov.ru,consultant.ru,garant.ru"
    tavily_api_key: str = ""
    tavily_base_url: str = "https://api.tavily.com"
    ocr_enabled: bool = True
    storage_dir: str = ".artifacts"
    storage_encryption_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="LEGAL_", extra="ignore")

    @property
    def allowed_source_domains_list(self) -> list[str]:
        return [domain.strip() for domain in self.allowed_source_domains.split(",") if domain.strip()]

    @property
    def storage_dir_path(self) -> Path:
        return Path(self.storage_dir)


@lru_cache
def get_settings() -> Settings:
    return Settings()

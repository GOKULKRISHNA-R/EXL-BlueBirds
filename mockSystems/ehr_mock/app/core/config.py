from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    ehr_api_token: str = "dev-ehr-token-change-me"
    ehr_base_url: str = "http://localhost:8000"
    log_level: str = "INFO"
    ehr_data_file: str | None = None
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

@lru_cache
def get_settings() -> Settings:
    return Settings()

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Keitaro Campaign Manager"
    keitaro_base_url: str = "https://tlgk.host/admin_api/v1"
    keitaro_api_key: str = ""
    database_url: str = "sqlite:///./app.db"
    campaign_prefix: str = "test_vdovichenko_"
    http_timeout: float = 600.0
    offer_cache_ttl: int = 60

    @property
    def normalized_prefix(self) -> str:
        prefix = self.campaign_prefix.strip().lower()
        if not prefix.startswith("test_"):
            prefix = f"test_{prefix.lstrip('test_')}"
        return prefix if prefix.endswith("_") else f"{prefix}_"

    @property
    def keitaro_headers(self) -> dict[str, str]:
        return {
            "Api-Key": self.keitaro_api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

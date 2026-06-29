import os
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql://nws_user:changeme@db:5432/nws_monitor"
    )
    api_user_agent: str = os.getenv("API_USER_AGENT", "(NWS-Monitor, user@example.com)")
    nwws_username: str | None = os.getenv("NWWS_USERNAME")
    nwws_password: str | None = os.getenv("NWWS_PASSWORD")
    retention_days: int = int(os.getenv("RETENTION_DAYS", "30"))
    port: int = int(os.getenv("PORT", "8000"))
    api_poll_interval: int = int(os.getenv("API_POLL_INTERVAL", "30"))

    @property
    def nwws_enabled(self) -> bool:
        return bool(self.nwws_username and self.nwws_password)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()

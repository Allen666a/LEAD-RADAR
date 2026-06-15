from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Lead Radar"
    database_url: str = "sqlite:///data/lead_radar.sqlite3"
    user_agent: str = "LeadRadar/0.1"
    wework_webhook_url: str = ""
    github_token: str = ""
    gitee_token: str = ""
    collector_interval_minutes: int = 30
    high_intent_threshold: int = 70
    rsshub_base_url: str = "http://127.0.0.1:1200"
    agent_auto_start_workers: int = 3
    agent_worker_poll_seconds: int = 5

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def database_path(self) -> Path | None:
        if not self.database_url.startswith("sqlite:///"):
            return None
        return Path(self.database_url.removeprefix("sqlite:///"))

    def rsshub_url(self, route: str) -> str:
        return self.rsshub_base_url.rstrip("/") + "/" + route.lstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()

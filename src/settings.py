from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "/app/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    config_path: str = "/config/config.yaml"
    dry_run: bool = False
    run_once: bool = False
    poll_interval_seconds: int = 86400
    poll_jitter_seconds: int = 1800


settings = Settings()

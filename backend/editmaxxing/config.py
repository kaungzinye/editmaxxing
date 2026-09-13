from pathlib import Path

from pydantic import PositiveFloat, PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    openai_api_key: str = ""
    editor_model: str = "gpt-6-astra"
    storage_root: Path = Path("data")
    public_base_url: str = "http://localhost:8000"
    cors_origins: list[str] = ["http://localhost:8081", "http://localhost:8082"]
    retention_hours: PositiveInt = 24
    upload_hours: PositiveInt = 24
    max_video_bytes: PositiveInt = 2 * 1024**3
    max_audio_bytes: PositiveInt = 24_000_000
    storage_quota_bytes: PositiveInt = 20 * 1024**3
    max_hook_duration_ms: PositiveInt = 600000
    part_size: PositiveInt = 4 * 1024**2
    signed_url_seconds: PositiveInt = 3600
    max_incoming_uploads: PositiveInt = 4
    upload_timeout_seconds: PositiveFloat = 300
    enable_fixtures: bool = False
    worker_enabled: bool = True

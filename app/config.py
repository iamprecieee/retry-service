from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./retry_service.db"
    worker_interval_ms: int = 500
    worker_batch_size: int = 50
    default_max_retries: int = 5
    default_backoff_ms: int = 1000
    max_wait_ms: int = 300_000

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

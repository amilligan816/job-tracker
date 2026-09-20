from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://jobtracker:change-me-in-dev@localhost:5432/jobtracker"

    # MinIO / S3. The public endpoint is what gets signed into URLs the browser
    # opens, which is a different host than the one the backend dials.
    s3_endpoint_url: str = "http://localhost:9000"
    s3_public_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "change-me-in-dev"
    s3_bucket: str = "job-tracker"
    s3_region: str = "us-east-1"
    presign_ttl_seconds: int = 900

    cors_origins: str = "http://localhost:5173"
    log_level: str = "INFO"

    # Assistant features are optional; without a key the /assistant routes 503.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def assistant_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()

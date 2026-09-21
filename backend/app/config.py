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

    # Assistant features are optional; with no credential the routes 503.
    anthropic_api_key: str = ""
    # An OAuth access token, for setups that authenticate that way instead.
    anthropic_auth_token: str = ""
    # Set when the credential lives somewhere the SDK finds on its own -- an
    # `ant auth login` profile on disk, or workload identity federation. We
    # can't detect those cheaply, so this says "trust the SDK's own lookup".
    anthropic_ambient_auth: bool = False
    anthropic_model: str = "claude-opus-5"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def assistant_enabled(self) -> bool:
        return bool(
            self.anthropic_api_key or self.anthropic_auth_token or self.anthropic_ambient_auth
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()

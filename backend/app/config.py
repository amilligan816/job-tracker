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

    # ---------------------------------------------------------------- mail sync
    # Gmail is read through a Google OAuth client you register yourself; with no
    # client configured the mail routes report "not configured" rather than 503,
    # since there is nothing transient about a missing client id.
    google_client_id: str = ""
    google_client_secret: str = ""
    # Where Google sends the user back. Must match the redirect URI registered on
    # the OAuth client exactly, so it is spelled out rather than derived.
    google_redirect_uri: str = "http://localhost:8000/api/mail/oauth/google/callback"
    # Where the callback bounces the browser once the account is connected.
    frontend_base_url: str = "http://localhost:5173"

    # Fernet key encrypting OAuth tokens at rest. Required to connect a mailbox:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    mail_token_key: str = ""

    # Background sync cadence. 0 disables the loop -- the manual "Sync now" button
    # and the API still work.
    mail_sync_interval_seconds: int = 900
    # How far back the first sync of a mailbox reaches.
    mail_lookback_days: int = 30
    # Ceiling on one run, so a long-dormant mailbox can't turn into a huge job.
    mail_max_messages_per_sync: int = 200
    # Let Claude adjudicate emails the heuristics are unsure about.
    mail_use_claude: bool = True
    # Heuristic confidence at or above which Claude is not consulted.
    mail_claude_confidence_floor: float = 0.75

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def assistant_enabled(self) -> bool:
        return bool(
            self.anthropic_api_key or self.anthropic_auth_token or self.anthropic_ambient_auth
        )

    @property
    def gmail_configured(self) -> bool:
        """Whether a mailbox can be connected at all.

        The token key counts: without it we would have nowhere safe to put the
        refresh token, and finding that out after the OAuth round trip is worse
        than saying so up front.
        """
        return bool(self.google_client_id and self.google_client_secret and self.mail_token_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()

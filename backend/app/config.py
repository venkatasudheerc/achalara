"""Application Configuration"""
from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings
from functools import lru_cache

# Always resolve .env relative to this file (backend/app/config.py → backend/.env)
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    """Application settings from environment variables"""

    database_url: str
    google_sheets_api_key: str = ""
    google_sheets_credentials_file: str = "./credentials.json"
    webull_app_key: str = ""
    webull_app_secret: str = ""
    snaptrade_client_id: str = ""
    snaptrade_consumer_key: str = ""
    # The SnapTrade userId the brokerage logins were linked under. With a
    # Personal key this is one fixed id for the key owner.
    snaptrade_user_id: str = ""
    python_env: str = "development"
    log_level: str = "INFO"
    port: int = 8000
    redis_url: str = "redis://localhost:6379/0"
    scheduler_enabled: bool = True
    # Comma-separated list of allowed CORS origins. Defaults to localhost dev server.
    # Set to the actual frontend URL(s) in production.
    cors_allow_origins: str = "http://localhost:5173"
    # How long a sign-in lasts before the person must sign in again.
    session_ttl_hours: int = 168

    @field_validator("database_url")
    @classmethod
    def _postgresql_scheme(cls, url: str) -> str:
        """Some hosts hand out ``postgres://``; SQLAlchemy only knows ``postgresql://``."""
        if url.startswith("postgres://"):
            return "postgresql://" + url[len("postgres://") :]
        return url

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    class Config:
        env_file = str(_ENV_FILE)
        # A local .env may still carry settings that have since been retired.
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """Get application settings (cached)"""
    return Settings()


settings = get_settings()

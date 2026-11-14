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
    # Plaid: clients link their own bank, card, loan and brokerage logins. One
    # developer account (these keys) serves every client. PLAID_ENV is sandbox
    # or production. PLAID_TOKEN_KEY encrypts each login's access key at rest
    # (a Fernet key). Empty keys: linking with Plaid is not offered.
    plaid_client_id: str = ""
    plaid_secret: str = ""
    plaid_env: str = "sandbox"
    plaid_token_key: str = ""
    # Where a bank that signs in by redirect (OAuth) returns to; built from the
    # domain in docker-compose.yml. Empty: Plaid's pop-up is used instead.
    plaid_redirect_uri: str = ""
    # How many logins the Plaid plan allows in all, across every client. The
    # trial allows 10, and a removed login never frees its place.
    plaid_max_logins: int = 10
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
    # A folder the server's own scripts write status files into (the nightly
    # backup's result), mounted read-only. Empty when there is none.
    status_dir: str = ""
    # A Telegram bot that messages the advisor when something needs a look.
    # Both empty: no alerts are sent.
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    # Email to clients (their invite and reset links), sent through Resend.
    # Either empty: no email is sent and links are passed on by hand.
    # Market data's settings (MD_DATABASE_URL, SEC_CONTACT_EMAIL,
    # OPENFIGI_API_KEY) are read by app/md/config.py, not here.
    resend_api_key: str = ""
    mail_from: str = ""  # e.g. Achalara <no-reply@mail.example.com>

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

"""Market data's own settings: only the names this package reads.

Read from the same ``.env`` and environment as the app's, so the setting names
do not change, but this package never imports the app's settings and can run
where the app's are not set up.
"""
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/md/config.py → backend/.env, as for the app.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class MdSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    # Market data's own database; empty means it shares the app's.
    md_database_url: str = ""
    database_url: str = ""
    log_level: str = "INFO"
    webull_app_key: str = ""
    webull_app_secret: str = ""
    # The SEC asks every request to EDGAR to carry a contact email. Empty: SEC
    # lookups are skipped.
    sec_contact_email: str = ""
    # OpenFIGI works without a key, at a lower rate; a key raises it.
    openfigi_api_key: str = ""
    # Years of stock and fund prices to keep; 0 keeps everything. Only ever set
    # where another copy keeps the full history (the laptop), as prices as traded
    # cannot be fetched again.
    md_history_years: int = 0

    @field_validator("md_database_url", "database_url")
    @classmethod
    def _postgresql_scheme(cls, url: str) -> str:
        """Some hosts hand out ``postgres://``; SQLAlchemy only knows ``postgresql://``."""
        if url.startswith("postgres://"):
            return "postgresql://" + url[len("postgres://") :]
        return url

    @property
    def url(self) -> str:
        """The database market data lives in."""
        url = self.md_database_url or self.database_url
        if not url:
            raise ValueError("Set MD_DATABASE_URL or DATABASE_URL for market data")
        return url

    @property
    def separate(self) -> bool:
        """Whether market data is in a different database from the app's."""
        return bool(self.md_database_url) and self.md_database_url != self.database_url


settings = MdSettings()

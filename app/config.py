from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://newsbot:newsbot@localhost:5432/newsbot"

    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_model_path: Path = Path("/models/all-MiniLM-L6-v2")
    embedding_dimensions: int = 384

    # LLM is served by the local pi agent (spawned as a subprocess).
    llm_provider: str = "pi"
    # Path to the pi executable. Defaults to whatever is on PATH.
    pi_bin: str = "pi"
    # Optional explicit provider passed to `pi --provider`. Empty -> pi default.
    pi_provider: str = ""
    # Optional thinking level passed to `pi --thinking` (off/minimal/low/medium/high/xhigh).
    pi_thinking: str = ""
    # Max seconds to wait for a single pi subprocess call.
    pi_timeout_seconds: int = 300
    # Optional host pi auth.json to import/copy into the container for OAuth.
    pi_auth_json_path: Path | None = None
    # Model patterns passed to `pi --model`. Empty -> let pi use its default.
    llm_smart_model: str = ""
    llm_cheap_model: str = ""
    llm_temperature: float = 0.1

    telegram_api_id: str | None = None
    telegram_api_hash: str | None = None
    telegram_user_session_path: Path = Path("/secrets/telethon.session")
    telegram_bot_token: str | None = None
    telegram_owner_chat_id: str | None = None

    gmail_client_secret_path: Path = Path("/secrets/gmail_client_secret.json")
    gmail_token_path: Path = Path("/secrets/gmail_token.json")
    gmail_scopes: str = "https://www.googleapis.com/auth/gmail.readonly"

    source_config_path: Path = Path("/config/sources.yaml")
    trusted_sources_path: Path = Path("/config/trusted_sources.yaml")
    trusted_social_accounts_path: Path = Path("/config/trusted_social_accounts.yaml")

    fetch_timeout_seconds: int = 20
    max_link_depth: int = 2
    min_trusted_documents: int = 1
    allow_x_official_posts: bool = True
    reject_telegram_links: bool = True
    reject_facebook_links: bool = True
    require_english: bool = True

    api_owner_token: str | None = Field(default=None, repr=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()

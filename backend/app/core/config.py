from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to this file so the server can be launched from any cwd
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), env_file_encoding="utf-8")

    openai_api_key: str
    openai_model: str = "gpt-4o"

    database_url: str  # postgresql+asyncpg://user:pass@host/db
    redis_url: str = "redis://localhost:6379/0"

    rag_top_k: int = 5
    rag_similarity_threshold: float = 0.56

    encryption_key: str  # Fernet key for encrypting PII (email)
    jwt_secret_key: str  # HS256 signing secret for access tokens
    jwt_expire_minutes: int = 480  # 8 hours

    # ── Job board integrations (all optional) ────────────────────────────────
    # LinkedIn UGC Posts API
    linkedin_access_token: str = ""
    linkedin_author_urn: str = ""   # e.g. "urn:li:person:ABC123" or "urn:li:organization:12345"

    # Indeed XML feed
    indeed_publisher_id: str = ""

    # Google Jobs / Indexing API (full JSON of a GCP service account key file)
    google_service_account_json: str = ""

    # Public base URL used in feed/page URLs sent to job boards
    app_base_url: str = "http://localhost:8000"

    # ── Email / SMTP (optional — app works without these) ─────────────────────
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@invictushiring.co"
    smtp_use_tls: bool = True

    # ── LangSmith tracing (optional) ─────────────────────────────────────────
    langsmith_api_key: str = ""
    langsmith_project: str = "InvictusHiring"
    langsmith_tracing: str = "True"
    langsmith_endpoint: str = "https://api.smith.langchain.com"


settings = Settings()

import os as _os  # noqa: E402
if settings.langsmith_api_key:
    _os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key)
    _os.environ.setdefault("LANGSMITH_ENDPOINT", settings.langsmith_endpoint)
    _os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)
    _os.environ.setdefault("LANGSMITH_TRACING", settings.langsmith_tracing)
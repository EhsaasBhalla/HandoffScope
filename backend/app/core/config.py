"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration for the HandoffScope backend.

    Values are loaded from environment variables or a .env file.
    """

    # ── Database ──────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+psycopg2://handoffscope:handoffscope_dev@localhost:5432/handoffscope"

    # ── Redis ─────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Security ──────────────────────────────────────────────
    SECRET_KEY: str = "change-me-in-production-use-a-long-random-string"
    CSRF_SECRET_KEY: str = "change-me-csrf-secret-key"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 days

    # ── CORS ──────────────────────────────────────────────────
    CORS_ORIGINS: str | list[str] = ["http://localhost:5173", "http://localhost:3000"]

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins safely from list, JSON array string, or comma-separated string."""
        if isinstance(self.CORS_ORIGINS, list):
            return self.CORS_ORIGINS
        if isinstance(self.CORS_ORIGINS, str):
            val = self.CORS_ORIGINS.strip()
            if val.startswith("[") and val.endswith("]"):
                try:
                    import json
                    return json.loads(val)
                except Exception:
                    pass
            parts = [x.strip() for x in val.split(",") if x.strip()]
            return parts if parts else ["*"]
        return ["*"]

    # ── GitHub App ────────────────────────────────────────────
    GITHUB_APP_ID: str = ""
    GITHUB_APP_PRIVATE_KEY_PATH: str = ""
    GITHUB_APP_WEBHOOK_SECRET: str = ""
    GITHUB_APP_CLIENT_ID: str = ""
    GITHUB_APP_CLIENT_SECRET: str = ""

    # ── LLM Provider ─────────────────────────────────────────
    LLM_PROVIDER: str = "gemini"
    LLM_API_KEY: str = ""
    LLM_MODEL_NAME: str = "gemini-1.5-flash"
    LLM_MAX_CALLS_PER_CASE: int = 50

    # ── Document Storage ──────────────────────────────────────
    UPLOAD_DIR: str = "./storage/uploads"
    MAX_UPLOAD_SIZE_MB: int = 50

    # ── Demo ──────────────────────────────────────────────────
    DEMO_USER_PASSWORD: str = "handoffscope-dev-2026"

    # ── Application ───────────────────────────────────────────
    APP_NAME: str = "HandoffScope"
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    DB_ECHO: bool = False

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()

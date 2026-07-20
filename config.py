from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
    )

    LLM_BASE_URL: str = ""
    LLM_API_KEY: str = ""
    LLM_MODEL: str = ""
    HF_TOKEN: str | None = None
    TAVILY_API_KEY: str = ""


settings = Settings()

IGNORED_FILES = {
    ".env",
}

EXCLUDED_DIRS = {
    ".git",
    "venv",
    ".venv",
    "__pycache__",
    "node_modules",
    ".next",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
}


# agent specific config.

REPO_DIR = Path(__file__).parent.resolve()
BASE_CONFIG_DIR = REPO_DIR / "scripts/amon/config"

SESSIONS_DIR = BASE_CONFIG_DIR / "sessions"

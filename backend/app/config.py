from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", BACKEND_DIR / ".env"),
        extra="ignore",
    )

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.8-flash"
    GEMINI_FALLBACK_MODEL: str = "gemini-3.5-flash-lite"
    SARVAM_API_KEY: str = ""
    DEMO_MODE: str = "live"  # live | record | replay
    TOOL_TRANSPORT: str = "mcp"  # mcp | direct
    SIM_LATENCY_MS: int = 80  # artificial latency of each mocked integration call (tests set 0)
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,https://qrwapsi.vercel.app"

    DATA_DIR: Path = BACKEND_DIR / "data"
    DEMO_CACHE_DIR: Path = BACKEND_DIR / "demo_cache"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.DATA_DIR / 'app.db'}"

    @property
    def checkpoint_path(self) -> Path:
        return self.DATA_DIR / "checkpoints.db"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()

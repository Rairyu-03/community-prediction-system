from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
import sys

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = BACKEND_ROOT.parent
IS_FROZEN = bool(getattr(sys, "frozen", False))
INSTALL_ROOT = Path(sys.executable).resolve().parent if IS_FROZEN else WORKSPACE_ROOT
WINDOWS_USER_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "CommunityPredictionSystem"
DATA_ROOT = Path(os.environ.get("COMMUNITY_DATA_ROOT", WINDOWS_USER_DATA if IS_FROZEN else WORKSPACE_ROOT)).resolve()
DEFAULT_DATABASE_URL = f"sqlite:///{((DATA_ROOT / 'community_prediction.db') if IS_FROZEN else (BACKEND_ROOT / 'data' / 'community_prediction.db')).as_posix()}"
DEFAULT_PROJECTS_ROOT = DATA_ROOT / "projects" if IS_FROZEN else WORKSPACE_ROOT / "runtime" / "projects"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "完整社区设施需求预测与动态匹配系统"
    api_prefix: str = "/api"
    database_url: str = DEFAULT_DATABASE_URL
    projects_root: Path = Field(default=DEFAULT_PROJECTS_ROOT)
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    host_api_token: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.projects_root.mkdir(parents=True, exist_ok=True)
    if settings.database_url.startswith("sqlite"):
        database_path = Path(settings.database_url.split("///", 1)[1])
        database_path.parent.mkdir(parents=True, exist_ok=True)
    return settings

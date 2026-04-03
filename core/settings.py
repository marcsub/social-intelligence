"""core/settings.py — Configuración global de la aplicación."""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    db_host: str = "localhost"
    db_port: int = 3306
    db_user: str = "social_app"
    db_password: str = ""
    db_name: str = "social_intelligence"

    panel_username: str = "admin"
    panel_password: str = ""
    jwt_secret: str = ""
    jwt_expire_hours: int = 12

    environment: str = "production"
    log_level: str = "INFO"

    @property
    def db_url(self) -> str:
        return (
            f"mysql+pymysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
            f"?charset=utf8mb4"
        )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()

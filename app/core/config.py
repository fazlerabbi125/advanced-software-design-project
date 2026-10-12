from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings
from sqlalchemy import URL
from app.utils.constants import CELERY_QUEUE_NAME, MAX_BIOMETRIC_IMAGE_BYTES


class Settings(BaseSettings):
    app_name: str = "BFS Gym API"
    enable_debug: bool = False
    postgres_host: str
    postgres_port: int = 5432
    postgres_db: str
    postgres_user: str
    postgres_password: SecretStr
    cache_redis_url: str
    celery_broker_url: str
    celery_result_backend: str
    celery_default_queue: str = CELERY_QUEUE_NAME
    jwt_access_secret_key: SecretStr
    jwt_refresh_secret_key: SecretStr
    jwt_algorithm: str = "HS256"
    jwt_issuer: str
    jwt_audience: str
    jwt_access_expiration: int = int(timedelta(minutes=15).total_seconds())
    jwt_refresh_expiration: int = int(timedelta(weeks=3).total_seconds())
    cors_allow_origins: list[str] = Field(default_factory=list)
    upload_root: Path
    biometric_image_max_bytes: int = MAX_BIOMETRIC_IMAGE_BYTES
    stripe_secret_key: SecretStr | None = None
    stripe_webhook_secret: SecretStr | None = None

    @property
    def sqlalchemy_url(self) -> URL:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    @property
    def sqlalchemy_url_string(self) -> str:
        return self.sqlalchemy_url.render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()

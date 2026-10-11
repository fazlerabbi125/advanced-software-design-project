from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.utils.constants import CELERY_QUEUE_NAME, MAX_BIOMETRIC_IMAGE_BYTES


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env.docker", extra="ignore")

    app_name: str
    app_environment: str
    database_url: str
    cache_redis_url: str
    celery_broker_url: str
    celery_result_backend: str
    celery_default_queue: str = CELERY_QUEUE_NAME
    jwt_access_secret_key: SecretStr
    jwt_refresh_secret_key: SecretStr
    jwt_algorithm: str
    jwt_issuer: str
    jwt_audience: str
    jwt_access_token_minutes: int
    jwt_refresh_token_days: int
    cors_allow_origins: list[str]
    upload_root: Path
    biometric_image_max_bytes: int = MAX_BIOMETRIC_IMAGE_BYTES
    stripe_secret_key: SecretStr | None = None
    stripe_webhook_secret: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()

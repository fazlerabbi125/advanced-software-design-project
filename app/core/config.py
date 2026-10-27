from datetime import timedelta
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings
from sqlalchemy import URL

from app.utils.constants import (
    MAX_BIOMETRIC_IMAGE_BYTES,
    VIP_ROOM_CAPACITY,
)


class Settings(BaseSettings):
    app_name: str = "BFS Gym API"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    enable_debug: bool = False
    postgres_host: str
    postgres_port: int = 5432
    postgres_db: str
    postgres_user: str
    postgres_password: SecretStr
    cache_redis_url: str
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
    vip_room_capacity: int = Field(default=VIP_ROOM_CAPACITY, gt=0)
    # Secret key of each face-recognition door scanner, mapped to the zone its door opens.
    scanner_device_keys: dict[str, str] = Field(default_factory=dict)
    # Run the waitlist-offer and no-show jobs in this process. Turn off in all but one
    # process when running several API workers.
    enable_booking_jobs: bool = True

    # --- Stripe payment settings ---
    # Use Stripe test keys (sk_test_...) for local development and demos.
    # Production keys must never be committed to the repository.
    stripe_secret_key: SecretStr
    stripe_webhook_secret: SecretStr
    # URLs Stripe redirects the member to after checkout completes or is abandoned.
    stripe_success_url: str = "http://localhost:8000/docs#/memberships/purchase_membership"
    stripe_cancel_url: str = "http://localhost:8000/docs#/memberships/purchase_membership"

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

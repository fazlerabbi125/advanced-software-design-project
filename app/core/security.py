from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash

from app.core.config import get_settings

password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return password_hasher.verify(password, password_hash)


def create_access_token(subject: UUID, role: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(seconds=settings.jwt_access_expiration),
    }
    if settings.jwt_issuer is not None:
        payload["iss"] = settings.jwt_issuer
    if settings.jwt_audience is not None:
        payload["aud"] = settings.jwt_audience

    return jwt.encode(
        payload,
        settings.jwt_access_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token(
    subject: UUID, family_id: str | None = None
) -> tuple[str, str, str, datetime]:
    settings = get_settings()
    now = datetime.now(UTC)
    jti = str(uuid4())
    expires_at = now + timedelta(seconds=settings.jwt_refresh_expiration)
    payload = {
        "sub": str(subject),
        "jti": jti,
        "family": family_id or str(uuid4()),
        "type": "refresh",
        "iat": now,
        "exp": expires_at,
    }
    if settings.jwt_issuer is not None:
        payload["iss"] = settings.jwt_issuer
    if settings.jwt_audience is not None:
        payload["aud"] = settings.jwt_audience

    token = jwt.encode(
        payload,
        settings.jwt_refresh_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return token, jti, payload["family"], expires_at


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    settings = get_settings()
    key = (
        settings.jwt_access_secret_key.get_secret_value()
        if expected_type == "access"
        else settings.jwt_refresh_secret_key.get_secret_value()
    )
    try:
        payload = jwt.decode(
            token,
            key,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
        )
    except InvalidTokenError as error:
        raise ValueError("invalid token") from error
    if payload.get("type") != expected_type:
        raise ValueError("invalid token type")
    return payload

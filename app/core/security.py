from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import uuid4

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash

from app.core.config import get_settings

password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return password_hasher.verify(password, password_hash)


def hash_token(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def create_access_token(subject: int, role: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "role": role,
        "type": "access",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_token_minutes),
    }
    return jwt.encode(
        payload,
        settings.jwt_access_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token(
    subject: int, family_id: str | None = None
) -> tuple[str, str, str, datetime]:
    settings = get_settings()
    now = datetime.now(UTC)
    jti = str(uuid4())
    expires_at = now + timedelta(days=settings.jwt_refresh_token_days)
    payload = {
        "sub": str(subject),
        "jti": jti,
        "family": family_id or str(uuid4()),
        "type": "refresh",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "exp": expires_at,
    }
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

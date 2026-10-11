from datetime import UTC, datetime


def build_cache_key(*parts: str) -> str:
    return ":".join(part.strip().lower() for part in parts if part.strip())


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def utc_now() -> datetime:
    return datetime.now(UTC)

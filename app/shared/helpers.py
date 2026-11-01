from datetime import UTC, datetime


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def utc_now() -> datetime:
    return datetime.now(UTC)

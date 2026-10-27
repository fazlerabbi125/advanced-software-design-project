from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import DateTime, func
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(AsyncAttrs, DeclarativeBase):
    pass


class IdMixin:
    id: Mapped[int] = mapped_column(primary_key=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

ASYNC_CASCADE = "save-update, merge, expunge, delete, delete-orphan"


def enum_values(enum_class: type[Enum]) -> list[str]:
    """Persist enum values rather than their Python member names."""
    return [str(member.value) for member in enum_class]

import base64
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


class PageParams(BaseModel):
    page: int = Field(ge=1)
    limit: int = Field(ge=1, le=MAX_PAGE_SIZE)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.limit


def get_page_params(
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> PageParams:
    return PageParams(page=page, limit=limit)


PageParamsDep = Annotated[PageParams, Depends(get_page_params)]


class PageMeta(BaseModel):
    page: int
    limit: int
    total_pages: int
    total_count: int


class PageResponse[ItemT](BaseModel):
    items: list[ItemT]
    meta: PageMeta


@dataclass(frozen=True, slots=True)
class PageResult[ItemT]:
    items: list[ItemT]
    meta: PageMeta


class CursorDirection(StrEnum):
    NEXT = "next"
    PREVIOUS = "previous"


class CursorParams(BaseModel):
    cursor: str | None = None
    direction: CursorDirection = CursorDirection.NEXT
    limit: int = Field(ge=1, le=MAX_PAGE_SIZE)
    values: tuple[str | int, ...] = ()


def encode_cursor(*values: str | int) -> str:
    encoded = json.dumps(values, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(encoded).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str | int, ...]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        values = json.loads(base64.urlsafe_b64decode(padded))
    except ValueError as error:
        raise ValueError("cursor must be a valid opaque cursor") from error
    if not isinstance(values, list) or not all(
        isinstance(value, (str, int)) and not isinstance(value, bool) for value in values
    ):
        raise ValueError("cursor must be a valid opaque cursor")
    return tuple(values)


def get_cursor_params(
    cursor: str | None = None,
    direction: CursorDirection = CursorDirection.NEXT,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> CursorParams:
    try:
        values = () if cursor is None else _decode_cursor(cursor)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    return CursorParams(cursor=cursor, direction=direction, limit=limit, values=values)


CursorParamsDep = Annotated[CursorParams, Depends(get_cursor_params)]


class CursorMeta(BaseModel):
    limit: int
    next_cursor: str | None
    previous_cursor: str | None
    has_next: bool
    has_previous: bool


class CursorResponse[ItemT](BaseModel):
    items: list[ItemT]
    meta: CursorMeta


@dataclass(frozen=True, slots=True)
class CursorResult[ItemT]:
    items: list[ItemT]
    meta: CursorMeta

import unittest

from fastapi import HTTPException
from pydantic import ValidationError

from app.shared.pagination import (
    CursorDirection,
    CursorParams,
    PageParams,
    encode_cursor,
    get_cursor_params,
    get_page_params,
)


class PaginationTests(unittest.TestCase):
    def test_page_parameters_have_defaults_and_enforce_boundaries(self) -> None:
        self.assertEqual(get_page_params().model_dump(), {"page": 1, "limit": 20})
        self.assertEqual(get_page_params(page=2, limit=7).offset, 7)
        with self.assertRaises(ValidationError):
            PageParams(page=0, limit=20)

    def test_cursor_round_trip_and_invalid_cursor(self) -> None:
        cursor = encode_cursor("2026-10-30T12:00:00+00:00", 3)
        params = get_cursor_params(cursor=cursor, direction=CursorDirection.PREVIOUS, limit=7)
        self.assertEqual(params.values, ("2026-10-30T12:00:00+00:00", 3))
        self.assertEqual(params.direction, CursorDirection.PREVIOUS)
        with self.assertRaises(HTTPException) as raised:
            get_cursor_params(cursor="not-a-cursor")
        self.assertEqual(raised.exception.status_code, 422)

    def test_cursor_rejects_boolean_values(self) -> None:
        with self.assertRaises(HTTPException):
            get_cursor_params(cursor=encode_cursor(True))
        self.assertEqual(CursorParams(limit=20).values, ())

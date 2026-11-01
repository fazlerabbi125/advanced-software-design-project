import unittest
from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.exceptions import AppError
from app.modules.auth.service import AuthService


class AuthServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_refresh_token_is_unauthorized(self) -> None:
        session = MagicMock()
        session.scalar = AsyncMock()
        with patch(
            "app.modules.auth.service.decode_token", side_effect=ValueError("invalid token")
        ):
            with self.assertRaises(AppError) as raised:
                await AuthService().rotate_refresh_token(session, "invalid")

        self.assertEqual(raised.exception.status_code, HTTPStatus.UNAUTHORIZED)
        session.scalar.assert_not_awaited()

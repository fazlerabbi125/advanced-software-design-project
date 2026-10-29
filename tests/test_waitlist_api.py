import os
import unittest
from datetime import timedelta
from unittest.mock import ANY, AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import AppError
from app.models import Booking, BookingStatus, User, WaitlistEntry, WaitlistStatus
from app.modules.bookings.eligibility import EligibilityFailure
from tests.test_booking_eligibility import NOW
from tests.test_booking_jobs import timetable_session

SETTINGS = {
    "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_DB": "unused",
    "POSTGRES_USER": "unused",
    "POSTGRES_PASSWORD": "unused",
    "CACHE_REDIS_URL": "redis://127.0.0.1:1",
    "JWT_ACCESS_SECRET_KEY": "test-only-access",
    "JWT_REFRESH_SECRET_KEY": "test-refresh",
    "JWT_ISSUER": "test",
    "JWT_AUDIENCE": "test",
    "UPLOAD_ROOT": "/tmp/bfs-test-unused",
    "STRIPE_SECRET_KEY": "sk_test_unused",
    "STRIPE_WEBHOOK_SECRET": "whsec_unused",
}


class WaitlistApiTests(unittest.TestCase):
    def setUp(self):
        # Import the router with test-only settings; overridden dependencies never connect.
        with patch.dict(os.environ, SETTINGS):
            from app.modules.auth.dependencies import get_current_user
            from app.modules.bookings.dependencies import get_booking_service
            from app.modules.bookings.endpoints.v1 import router
        self.service = AsyncMock()
        app = FastAPI()
        app.include_router(router)
        self.current_user_id = uuid4()
        app.dependency_overrides[get_current_user] = lambda: User(id=self.current_user_id)
        app.dependency_overrides[get_booking_service] = lambda: self.service
        self.client = TestClient(app)

    def test_accepting_an_offer_returns_the_booking(self):
        session = timetable_session()
        self.service.accept_offer.return_value = Booking(
            id=3,
            timetable_session_id=1,
            resource_name=session.resource_name,
            resource_type=session.resource_type,
            starts_at=session.starts_at,
            ends_at=session.ends_at,
            status=BookingStatus.CONFIRMED,
        )

        response = self.client.post("/bookings/waitlist/5/accept")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "confirmed")
        self.service.accept_offer.assert_awaited_once_with(ANY, ANY, self.current_user_id, 5)

    def test_accept_errors(self):
        failure = AppError(
            "booking eligibility failed", 422, [EligibilityFailure("weekly_limit", "limit reached")]
        )
        cases = (
            (AppError("missing", 404), 404),
            (AppError("no open offer", 409), 409),
            (failure, 422),
        )
        for error, expected in cases:
            with self.subTest(error=type(error).__name__):
                self.service.accept_offer.side_effect = error
                response = self.client.post("/bookings/waitlist/5/accept")
                self.assertEqual(response.status_code, expected)
        self.assertEqual(response.json()["detail"][0]["code"], "weekly_limit")

    def test_my_waitlist_shows_when_an_open_offer_expires(self):
        session = timetable_session()
        offered = WaitlistEntry(
            id=2, session_id=1, status=WaitlistStatus.OFFERED, offered_at=NOW, session=session
        )
        waiting = WaitlistEntry(id=1, session_id=1, status=WaitlistStatus.WAITING, session=session)
        self.service.list_waitlist_for_user.return_value = [offered, waiting]

        body = self.client.get("/bookings/waitlist/me").json()

        expires = (NOW + timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
        self.assertEqual(
            [(item["status"], item["offer_expires_at"]) for item in body],
            [("offered", expires), ("waiting", None)],
        )


if __name__ == "__main__":
    unittest.main()

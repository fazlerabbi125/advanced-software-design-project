import os
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import AppError
from app.models.auth import User
from app.modules.bookings.eligibility import EligibilityFailure
from tests.settings import TEST_ENVIRONMENT


class BookingApiTests(unittest.TestCase):
    def test_all_failures_are_returned_as_422(self):
        # Import the router with test-only settings; overridden dependencies never connect.
        with patch.dict(os.environ, TEST_ENVIRONMENT):
            from app.modules.auth.dependencies import get_current_user
            from app.modules.bookings.dependencies import get_booking_service
            from app.modules.bookings.endpoints.v1 import router
        service = AsyncMock()
        failures = [
            EligibilityFailure("plan_entitlement", "not included"),
            EligibilityFailure("weekly_limit", "limit reached"),
        ]
        service.create.side_effect = AppError("booking eligibility failed", 422, failures)
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: User(id=uuid4())
        app.dependency_overrides[get_booking_service] = lambda: service
        with TestClient(app) as client:
            response = client.post(
                "/bookings",
                json={"timetable_session_id": 1},
            )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"],
            [
                {"code": "plan_entitlement", "message": "not included"},
                {"code": "weekly_limit", "message": "limit reached"},
            ],
        )

import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.auth import User
from app.modules.bookings.eligibility import BookingEligibilityError, EligibilityFailure


class BookingApiTests(unittest.TestCase):
    def test_all_failures_are_returned_as_422(self):
        # Import the router with test-only settings; overridden dependencies never connect.
        settings = {
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_DB": "unused",
            "POSTGRES_USER": "unused",
            "POSTGRES_PASSWORD": "unused",
            "CACHE_REDIS_URL": "redis://127.0.0.1:1",
            "CELERY_BROKER_URL": "redis://127.0.0.1:1",
            "CELERY_RESULT_BACKEND": "redis://127.0.0.1:1",
            "JWT_ACCESS_SECRET_KEY": "test-only-access",
            "JWT_REFRESH_SECRET_KEY": "test-refresh",
            "JWT_ISSUER": "test",
            "JWT_AUDIENCE": "test",
            "UPLOAD_ROOT": "/tmp/bfs-test-unused",
        }
        with patch.dict(os.environ, settings):
            from app.modules.auth.dependencies import get_current_user
            from app.modules.bookings.api_v1 import router
            from app.modules.bookings.dependencies import get_booking_service
        service = AsyncMock()
        failures = [
            EligibilityFailure("plan_entitlement", "not included"),
            EligibilityFailure("weekly_limit", "limit reached"),
        ]
        service.create.side_effect = BookingEligibilityError(failures)
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: User(id=1)
        app.dependency_overrides[get_booking_service] = lambda: service
        with TestClient(app) as client:
            response = client.post(
                "/bookings",
                json={"session_id": 1},
            )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"],
            [
                {"code": "plan_entitlement", "message": "not included"},
                {"code": "weekly_limit", "message": "limit reached"},
            ],
        )

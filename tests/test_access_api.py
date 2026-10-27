import os
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.access import AccessEvent, AccessLog, AccessZone
from app.models.auth import User, UserRole
from tests.settings import TEST_ENVIRONMENT


class ManualCheckInApiTests(unittest.TestCase):
    def setUp(self):
        # Import the router with test-only settings; overridden dependencies never connect.
        with patch.dict(os.environ, TEST_ENVIRONMENT):
            from app.modules.access.api_v1 import router
            from app.modules.access.dependencies import get_access_service
            from app.modules.auth.dependencies import get_current_user
        self.service = AsyncMock()
        self.member_id = uuid4()
        self.staff_id = uuid4()
        self.service.check_in.return_value = AccessLog(
            id=1,
            member_id=self.member_id,
            event=AccessEvent.MANUAL_CHECK_IN,
            zone=AccessZone.VIP_SAUNA.value,
            source="manual",
            occurred_at=datetime(2026, 10, 26, 18, 0, tzinfo=UTC),
            performed_by_staff_id=self.staff_id,
            staff_reason="Scanner offline",
        )
        self.current_user = User(id=self.staff_id, role=UserRole.STAFF)
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: self.current_user
        app.dependency_overrides[get_access_service] = lambda: self.service
        self.client = TestClient(app)

    def post(self, **body):
        payload = {
            "member_id": str(self.member_id),
            "zone": "vip_sauna",
            "reason": "  Scanner offline  ",
        } | body
        return self.client.post("/access/manual-check-in", json=payload)

    def test_staff_check_in_records_who_and_why(self):
        response = self.post()

        self.assertEqual(response.status_code, 201)
        self.service.check_in.assert_awaited_once_with(
            self.member_id,
            AccessZone.VIP_SAUNA,
            source="manual",
            event=AccessEvent.MANUAL_CHECK_IN,
            staff_id=self.staff_id,
            reason="Scanner offline",
        )
        body = response.json()
        self.assertEqual(body["performed_by_staff_id"], str(self.staff_id))
        self.assertEqual(body["staff_reason"], "Scanner offline")

    def test_reason_is_required(self):
        for reason in (None, "", "  "):
            with self.subTest(reason=reason):
                payload = {"member_id": str(self.member_id), "zone": "vip_sauna"}
                if reason is not None:
                    payload["reason"] = reason
                response = self.client.post("/access/manual-check-in", json=payload)
                self.assertEqual(response.status_code, 422)
        self.service.check_in.assert_not_awaited()

    def test_member_id_is_required(self):
        response = self.client.post(
            "/access/manual-check-in", json={"zone": "vip_sauna", "reason": "Scanner offline"}
        )

        self.assertEqual(response.status_code, 422)
        self.service.check_in.assert_not_awaited()

    def test_members_cannot_check_others_in_manually(self):
        self.current_user = User(id=self.member_id, role=UserRole.MEMBER)

        response = self.post()

        self.assertEqual(response.status_code, 403)
        self.service.check_in.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

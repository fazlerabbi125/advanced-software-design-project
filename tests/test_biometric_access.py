import os
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.access import AccessEvent, AccessLog, AccessZone, DeniedAccessReason
from app.models.members import MemberProfile
from app.modules.access.biometric_service import (
    BiometricAccessService,
    BiometricScanDeniedError,
    ScannerDevice,
)
from app.modules.access.policies import AccessDeniedError, ZoneFullError
from app.modules.access.schemas import DeviceCheckInRequest
from app.modules.access.service import CheckInResult
from tests.settings import TEST_ENVIRONMENT


class BiometricAccessServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.session = MagicMock()
        self.session.scalar = AsyncMock()
        self.access = MagicMock()
        self.access.check_in = AsyncMock()
        self.service = BiometricAccessService(self.session, self.access)
        self.scanner = ScannerDevice(AccessZone.VIP_SAUNA, "a" * 64)
        self.template_id = uuid4()
        self.settings = SimpleNamespace(biometric_min_confidence=0.80)

    def payload(self, confidence: float = 0.92) -> DeviceCheckInRequest:
        return DeviceCheckInRequest(template_id=self.template_id, confidence=confidence)

    async def test_known_template_uses_direct_lookup_and_checks_only_its_member(self) -> None:
        user_id = uuid4()
        self.session.scalar.return_value = MemberProfile(
            user_id=user_id,
            name="Member",
            biometric_template_id=self.template_id,
        )
        expected = MagicMock(spec=CheckInResult)
        self.access.check_in.return_value = expected

        with patch("app.modules.access.biometric_service.get_settings", return_value=self.settings):
            result = await self.service.check_in(self.payload(), self.scanner)

        self.assertIs(result, expected)
        statement = self.session.scalar.await_args.args[0]
        self.assertIn("member_profiles.biometric_template_id", str(statement))
        self.access.check_in.assert_awaited_once_with(
            user_id, AccessZone.VIP_SAUNA, source="face_recognition"
        )
        self.session.add.assert_not_called()

    async def test_unknown_template_is_audited_without_enumerating_profiles(self) -> None:
        self.session.scalar.return_value = None

        with patch("app.modules.access.biometric_service.get_settings", return_value=self.settings):
            with self.assertRaisesRegex(BiometricScanDeniedError, "unknown biometric template"):
                await self.service.check_in(self.payload(), self.scanner)

        statement = self.session.scalar.await_args.args[0]
        self.assertIn("member_profiles.biometric_template_id", str(statement))
        self.access.check_in.assert_not_awaited()
        attempt = self.session.add.call_args.args[0]
        self.assertEqual(attempt.reason, DeniedAccessReason.UNKNOWN_TEMPLATE)
        self.assertEqual(attempt.biometric_template_id, self.template_id)

    async def test_low_confidence_is_audited_before_profile_lookup(self) -> None:
        with patch("app.modules.access.biometric_service.get_settings", return_value=self.settings):
            with self.assertRaisesRegex(BiometricScanDeniedError, "confidence is too low"):
                await self.service.check_in(self.payload(0.79), self.scanner)

        self.session.scalar.assert_not_awaited()
        attempt = self.session.add.call_args.args[0]
        self.assertEqual(attempt.reason, DeniedAccessReason.LOW_CONFIDENCE)

    async def test_access_and_capacity_denials_are_audited(self) -> None:
        self.session.scalar.return_value = MemberProfile(
            user_id=uuid4(), name="Member", biometric_template_id=self.template_id
        )
        for error, expected_reason, expected_status in (
            (AccessDeniedError("membership is inactive"), DeniedAccessReason.ACCESS_DENIED, 403),
            (ZoneFullError(AccessZone.VIP_SAUNA, 2), DeniedAccessReason.ZONE_FULL, 409),
        ):
            with self.subTest(error=type(error).__name__):
                self.access.check_in.side_effect = error
                with patch(
                    "app.modules.access.biometric_service.get_settings", return_value=self.settings
                ):
                    with self.assertRaises(BiometricScanDeniedError) as raised:
                        await self.service.check_in(self.payload(), self.scanner)
                self.assertEqual(raised.exception.status_code, expected_status)
                self.assertEqual(self.session.add.call_args.args[0].reason, expected_reason)


class DeviceCheckInApiTests(unittest.TestCase):
    def setUp(self) -> None:
        with patch.dict(os.environ, TEST_ENVIRONMENT):
            from app.core.database import get_db_session
            from app.modules.access.dependencies import (
                get_biometric_access_service,
                get_scanner_device,
            )
            from app.modules.access.endpoints.v1 import router

        self.session = MagicMock()
        self.session.commit = AsyncMock()
        self.session.rollback = AsyncMock()
        self.service = MagicMock()
        self.service.check_in = AsyncMock()
        self.template_id = uuid4()
        self.scanner = ScannerDevice(AccessZone.VIP_SAUNA, "a" * 64)
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db_session] = lambda: self.session
        app.dependency_overrides[get_biometric_access_service] = lambda: self.service
        app.dependency_overrides[get_scanner_device] = lambda: self.scanner
        self.client = TestClient(app)

    def request(self, confidence: float = 0.92):
        return self.client.post(
            "/access/device-check-in",
            headers={"X-Device-Key": "not-used-by-overridden-dependency"},
            json={"template_id": str(self.template_id), "confidence": confidence},
        )

    def test_device_endpoint_forwards_template_and_confidence(self) -> None:
        member_id = uuid4()
        self.service.check_in.return_value = CheckInResult(
            access_log=AccessLog(
                id=1,
                member_id=member_id,
                event=AccessEvent.CHECK_IN,
                zone=AccessZone.VIP_SAUNA.value,
                source="face_recognition",
                occurred_at=datetime(2026, 10, 28, tzinfo=UTC),
            ),
            took_new_place=True,
        )

        response = self.request()

        self.assertEqual(response.status_code, 201)
        payload, scanner = self.service.check_in.await_args.args
        self.assertEqual(payload.template_id, self.template_id)
        self.assertEqual(payload.confidence, 0.92)
        self.assertIs(scanner, self.scanner)
        self.session.commit.assert_awaited_once()

    def test_denied_scan_commits_audit_record_before_returning_error(self) -> None:
        self.service.check_in.side_effect = BiometricScanDeniedError(
            "unknown biometric template", 403
        )

        response = self.request()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "unknown biometric template")
        self.session.commit.assert_awaited_once()
        self.session.rollback.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

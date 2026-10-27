import unittest
from unittest.mock import AsyncMock, MagicMock

import app.models  # noqa: F401  (registers every model so User can be created)
from app.models.access import AccessEvent, AccessZone
from app.models.auth import User
from app.modules.access.policies import AccessDeniedError
from app.modules.access.service import AccessService


class CheckInAccountTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self, member):
        session = MagicMock()
        session.get = AsyncMock(return_value=member)
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        policy = MagicMock()
        policy.check = AsyncMock(return_value=True)
        service = AccessService(
            session, policies={AccessZone.VIP_SAUNA: policy}, occupancy=MagicMock()
        )
        return service, session, policy

    async def test_disabled_account_is_refused_before_a_place_is_taken(self):
        disabled = User(email="member@example.test", password_hash="unused", is_active=False)
        service, session, policy = self.make_service(disabled)

        with self.assertRaises(AccessDeniedError):
            await service.check_in(3, AccessZone.VIP_SAUNA, source="face_recognition")

        policy.check.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_unknown_member_is_refused(self):
        service, session, policy = self.make_service(None)

        with self.assertRaises(AccessDeniedError):
            await service.check_in(999, AccessZone.VIP_SAUNA, source="face_recognition")

        policy.check.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_active_account_goes_on_to_the_zone_rules(self):
        active = User(email="member@example.test", password_hash="unused", is_active=True)
        service, session, policy = self.make_service(active)

        await service.check_in(3, AccessZone.VIP_SAUNA, source="face_recognition")

        policy.check.assert_awaited_once_with(3, AccessZone.VIP_SAUNA)
        session.commit.assert_awaited_once()


class ManualCheckInTests(unittest.IsolatedAsyncioTestCase):
    make_service = CheckInAccountTests.make_service

    async def test_manual_check_in_records_the_staff_member_and_reason(self):
        active = User(email="member@example.test", password_hash="unused", is_active=True)
        service, session, policy = self.make_service(active)

        await service.check_in(
            3,
            AccessZone.VIP_SAUNA,
            source="manual",
            event=AccessEvent.MANUAL_CHECK_IN,
            staff_id=7,
            reason="Scanner offline",
        )

        access_log = session.add.call_args.args[0]
        self.assertEqual(access_log.event, AccessEvent.MANUAL_CHECK_IN)
        self.assertEqual(access_log.performed_by_staff_id, 7)
        self.assertEqual(access_log.staff_reason, "Scanner offline")
        policy.check.assert_awaited_once_with(3, AccessZone.VIP_SAUNA)

    async def test_manual_check_in_without_staff_or_reason_is_refused(self):
        active = User(email="member@example.test", password_hash="unused", is_active=True)
        service, session, policy = self.make_service(active)

        for staff_id, reason in ((None, "Scanner offline"), (7, None), (7, "")):
            with self.subTest(staff_id=staff_id, reason=reason):
                with self.assertRaises(ValueError):
                    await service.check_in(
                        3,
                        AccessZone.VIP_SAUNA,
                        source="manual",
                        event=AccessEvent.MANUAL_CHECK_IN,
                        staff_id=staff_id,
                        reason=reason,
                    )

        policy.check.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_scanner_check_in_has_no_staff_details(self):
        active = User(email="member@example.test", password_hash="unused", is_active=True)
        service, session, _ = self.make_service(active)

        await service.check_in(3, AccessZone.VIP_SAUNA, source="face_recognition")

        access_log = session.add.call_args.args[0]
        self.assertIsNone(access_log.performed_by_staff_id)
        self.assertIsNone(access_log.staff_reason)


if __name__ == "__main__":
    unittest.main()

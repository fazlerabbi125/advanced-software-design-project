import unittest
from unittest.mock import AsyncMock, MagicMock

import app.models  # noqa: F401  (registers every model so User can be created)
from app.models.access import AccessZone
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


if __name__ == "__main__":
    unittest.main()

import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.auth import User, UserRole
from app.models.memberships import MembershipEntitlement, MembershipPlan, PlanEntitlement
from app.modules.memberships.service import PlanNameTakenError, PlanNotFoundError
from tests.settings import TEST_ENVIRONMENT

NEW_PLAN = {
    "name": "  Student  ",
    "price_minor": 2500,
    "currency": "eur",
    "booking_window_days": 2,
    "weekly_booking_limit": 4,
    "entitlements": ["gym_floor_access", "class_booking"],
}


def stored_plan(**fields):
    values = {
        "id": 4,
        "name": "Student",
        "is_active": True,
        "price_minor": 2500,
        "currency": "EUR",
        "duration_days": 30,
        "booking_window_days": 2,
        "weekly_booking_limit": 4,
    } | fields
    plan = MembershipPlan(**values)
    plan.entitlements = [
        PlanEntitlement(entitlement=MembershipEntitlement.GYM_FLOOR_ACCESS),
        PlanEntitlement(entitlement=MembershipEntitlement.CLASS_BOOKING),
    ]
    return plan


class PlanManagementApiTests(unittest.TestCase):
    def setUp(self):
        # Import the router with test-only settings; overridden dependencies never connect.
        with patch.dict(os.environ, TEST_ENVIRONMENT):
            from app.modules.auth.dependencies import get_current_user
            from app.modules.memberships.api_v1 import router
            from app.modules.memberships.dependencies import get_membership_service
        self.service = AsyncMock()
        self.service.create_plan.return_value = stored_plan()
        self.service.update_plan.return_value = stored_plan(weekly_booking_limit=6)
        self.current_user = User(id=1, role=UserRole.MANAGER)
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: self.current_user
        app.dependency_overrides[get_membership_service] = lambda: self.service
        self.client = TestClient(app)

    def test_manager_creates_a_plan(self):
        response = self.client.post("/memberships/plans", json=NEW_PLAN)

        self.assertEqual(response.status_code, 201)
        self.service.create_plan.assert_awaited_once_with(
            name="Student",
            price_minor=2500,
            currency="EUR",
            duration_days=30,
            booking_window_days=2,
            weekly_booking_limit=4,
            entitlements={
                MembershipEntitlement.GYM_FLOOR_ACCESS,
                MembershipEntitlement.CLASS_BOOKING,
            },
        )
        body = response.json()
        self.assertEqual(body["weekly_booking_limit"], 4)
        self.assertEqual(body["entitlements"], ["class_booking", "gym_floor_access"])

    def test_staff_and_members_cannot_manage_plans(self):
        for role in (UserRole.STAFF, UserRole.MEMBER):
            with self.subTest(role=role):
                self.current_user = User(id=2, role=role)
                requests = (
                    self.client.post("/memberships/plans", json=NEW_PLAN),
                    self.client.patch("/memberships/plans/4", json={"price_minor": 1}),
                    self.client.delete("/memberships/plans/4"),
                    self.client.get("/memberships/plans/all"),
                )
                self.assertEqual([item.status_code for item in requests], [403] * 4)
        self.service.create_plan.assert_not_awaited()
        self.service.update_plan.assert_not_awaited()
        self.service.deactivate_plan.assert_not_awaited()

    def test_invalid_plans_are_rejected(self):
        invalid = (
            {"price_minor": 0},
            {"weekly_booking_limit": -1},
            {"currency": "EURO"},
            {"entitlements": []},
            {"entitlements": ["free_coffee"]},
            {"name": "   "},
        )
        for change in invalid:
            with self.subTest(change=change):
                response = self.client.post("/memberships/plans", json=NEW_PLAN | change)
                self.assertEqual(response.status_code, 422)
        self.service.create_plan.assert_not_awaited()

    def test_duplicate_name_is_a_conflict(self):
        self.service.create_plan.side_effect = PlanNameTakenError("taken")

        response = self.client.post("/memberships/plans", json=NEW_PLAN)

        self.assertEqual(response.status_code, 409)

    def test_update_sends_only_the_fields_given(self):
        response = self.client.patch(
            "/memberships/plans/4", json={"weekly_booking_limit": 6, "name": None}
        )

        self.assertEqual(response.status_code, 200)
        self.service.update_plan.assert_awaited_once_with(
            4, entitlements=None, weekly_booking_limit=6
        )
        self.assertEqual(response.json()["weekly_booking_limit"], 6)

    def test_update_of_unknown_plan_is_not_found(self):
        self.service.update_plan.side_effect = PlanNotFoundError("missing")

        response = self.client.patch("/memberships/plans/99", json={"price_minor": 3000})

        self.assertEqual(response.status_code, 404)

    def test_deactivate(self):
        self.assertEqual(self.client.delete("/memberships/plans/4").status_code, 204)
        self.service.deactivate_plan.assert_awaited_once_with(4)

        self.service.deactivate_plan.side_effect = PlanNotFoundError("missing")
        self.assertEqual(self.client.delete("/memberships/plans/99").status_code, 404)


if __name__ == "__main__":
    unittest.main()

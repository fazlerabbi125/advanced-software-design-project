import os
import unittest
from unittest.mock import ANY, AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import AppError
from app.models.auth import User, UserRole
from app.models.facilities import EquipmentFault, EquipmentUnit, FaultStatus
from app.modules.bookings.outages import CancelledBooking, MovedSlot, OutageOutcome
from tests.settings import TEST_ENVIRONMENT
from tests.test_booking_eligibility import NOW

MEMBER_ID, STAFF_ID = uuid4(), uuid4()


def unit(**fields):
    return EquipmentUnit(
        **(
            {
                "id": 2,
                "name": "Squat Rack 2",
                "equipment_type": "squat_rack",
                "zone": "gym_floor",
                "in_service": True,
            }
            | fields
        )
    )


def fault(**fields):
    values = {
        "id": 7,
        "unit_id": 2,
        "reported_by_id": MEMBER_ID,
        "description": "The safety catch is bent",
        "status": FaultStatus.REPORTED,
        "created_at": NOW,
        "reviewed_by_id": None,
        "reviewed_at": None,
        "resolved_by_id": None,
        "resolved_at": None,
    }
    return EquipmentFault(**(values | fields))


class EquipmentApiTests(unittest.TestCase):
    def setUp(self):
        # Import the router with test-only settings; overridden dependencies never connect.
        with patch.dict(os.environ, TEST_ENVIRONMENT):
            from app.modules.auth.dependencies import get_current_user
            from app.modules.facilities.dependencies import (
                get_facilities_service,
                get_outage_handler,
            )
            from app.modules.facilities.endpoints.v1 import router
        self.service = AsyncMock()
        self.outages = AsyncMock()
        self.current_user = User(id=STAFF_ID, role=UserRole.STAFF)
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: self.current_user
        app.dependency_overrides[get_facilities_service] = lambda: self.service
        app.dependency_overrides[get_outage_handler] = lambda: self.outages
        self.client = TestClient(app)

    def test_members_report_faults_but_cannot_manage_them(self):
        self.current_user = User(id=MEMBER_ID, role=UserRole.MEMBER)
        self.service.report_fault.return_value = fault()
        self.service.list_units.return_value = [unit()]

        report = self.client.post(
            "/equipment/2/faults", json={"description": "  The safety catch is bent "}
        )
        self.assertEqual(report.status_code, 201)
        self.service.report_fault.assert_awaited_once_with(
            ANY, 2, MEMBER_ID, "The safety catch is bent"
        )
        self.assertEqual(self.client.get("/equipment").json()[0]["name"], "Squat Rack 2")

        staff_only = (
            self.client.post("/equipment", json={"name": "Rack 9", "equipment_type": "squat rack"}),
            self.client.get("/equipment/faults"),
            self.client.post("/equipment/faults/7/confirm"),
            self.client.post("/equipment/faults/7/dismiss"),
            self.client.post("/equipment/faults/7/resolve"),
        )
        self.assertEqual([item.status_code for item in staff_only], [403] * 5)

    def test_staff_filter_faults_by_status(self):
        self.service.list_faults.return_value = [fault()]
        response = self.client.get("/equipment/faults?status=reported")
        self.assertEqual(response.status_code, 200)
        self.service.list_faults.assert_awaited_once_with(ANY, FaultStatus.REPORTED)
        self.assertEqual(self.client.get("/equipment/faults?status=broken").status_code, 422)

    def test_report_validation_and_unknown_unit(self):
        for body in ({"description": "no"}, {"description": "x" * 1001}, {}):
            with self.subTest(body=body):
                self.assertEqual(
                    self.client.post("/equipment/2/faults", json=body).status_code, 422
                )
        self.service.report_fault.side_effect = AppError("missing", 404)
        response = self.client.post("/equipment/99/faults", json={"description": "Broken"})
        self.assertEqual(response.status_code, 404)

    def test_confirm_lists_every_affected_member(self):
        confirmed = fault(status=FaultStatus.CONFIRMED, reviewed_by_id=STAFF_ID, reviewed_at=NOW)
        self.service.confirm_fault.return_value = (confirmed, unit(id=1, in_service=False))
        self.outages.handle.return_value = OutageOutcome(
            moved=[MovedSlot(4, "Squat Rack 1", "Squat Rack 2", [MEMBER_ID])],
            cancelled=[CancelledBooking(9, 5, MEMBER_ID)],
        )

        response = self.client.post("/equipment/faults/7/confirm")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["fault"]["status"], "confirmed")
        self.assertEqual(body["moved_slots"][0]["to_unit"], "Squat Rack 2")
        self.assertEqual(body["cancelled_bookings"][0]["booking_id"], 9)
        self.outages.handle.assert_awaited_once_with(ANY, ANY, ANY)

    def test_fault_errors(self):
        for method, path in (
            ("confirm_fault", "confirm"),
            ("dismiss_fault", "dismiss"),
            ("resolve_fault", "resolve"),
        ):
            with self.subTest(path=path):
                getattr(self.service, method).side_effect = AppError("missing", 404)
                self.assertEqual(self.client.post(f"/equipment/faults/7/{path}").status_code, 404)
                getattr(self.service, method).side_effect = AppError("wrong state", 409)
                self.assertEqual(self.client.post(f"/equipment/faults/7/{path}").status_code, 409)
        self.outages.handle.assert_not_awaited()

    def test_register_unit(self):
        self.service.register_unit.return_value = unit()
        response = self.client.post(
            "/equipment", json={"name": " Squat Rack 2 ", "equipment_type": "Squat rack"}
        )
        self.assertEqual(response.status_code, 201)
        self.service.register_unit.assert_awaited_once_with(
            ANY, "Squat Rack 2", "Squat rack", "gym_floor"
        )
        self.service.register_unit.side_effect = AppError("taken", 409)
        response = self.client.post(
            "/equipment", json={"name": "Squat Rack 2", "equipment_type": "squat rack"}
        )
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()

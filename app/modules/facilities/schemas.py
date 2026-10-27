from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.models.facilities import FaultStatus

UnitName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
EquipmentType = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)
]
Zone = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
FaultDescription = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)
]


class RegisterUnitRequest(BaseModel):
    name: UnitName
    equipment_type: EquipmentType
    zone: Zone = "gym_floor"


class EquipmentUnitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    equipment_type: str
    zone: str
    in_service: bool


class ReportFaultRequest(BaseModel):
    description: FaultDescription


class FaultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    unit_id: int
    reported_by_id: UUID
    description: str
    status: FaultStatus
    created_at: datetime
    reviewed_by_id: UUID | None
    reviewed_at: datetime | None
    resolved_by_id: UUID | None
    resolved_at: datetime | None


class MovedSlotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: int
    from_unit: str
    to_unit: str
    member_ids: list[UUID]


class CancelledBookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    booking_id: int
    session_id: int
    member_id: UUID


class ConfirmFaultResponse(BaseModel):
    """The confirmed fault and every member whose future slot moved or was cancelled."""

    fault: FaultResponse
    moved_slots: list[MovedSlotResponse]
    cancelled_bookings: list[CancelledBookingResponse]

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.models.access import AccessZone, DeniedAccessAttempt, DeniedAccessReason
from app.models.members import MemberProfile
from app.modules.access.schemas import DeviceCheckInRequest
from app.modules.access.service import AccessService, CheckInResult


@dataclass(frozen=True, slots=True)
class ScannerDevice:
    zone: AccessZone
    key_fingerprint: str


class BiometricAccessService:
    """Applies trusted scanner matches without loading every member profile."""

    def __init__(self, access: AccessService) -> None:
        self.access = access

    async def check_in(
        self, session: AsyncSession, payload: DeviceCheckInRequest, scanner: ScannerDevice
    ) -> CheckInResult:
        if payload.confidence < get_settings().biometric_min_confidence:
            await self._record_denial(session, payload, scanner, DeniedAccessReason.LOW_CONFIDENCE)
            raise AppError("biometric confidence is too low", 403)

        profile = await session.scalar(
            select(MemberProfile).where(MemberProfile.biometric_template_id == payload.template_id)
        )
        if profile is None:
            await self._record_denial(
                session, payload, scanner, DeniedAccessReason.UNKNOWN_TEMPLATE
            )
            raise AppError("unknown biometric template", 403)

        try:
            return await self.access.check_in(
                session, profile.user_id, scanner.zone, source="face_recognition"
            )
        except AppError as error:
            reason = (
                DeniedAccessReason.ZONE_FULL
                if error.status_code == 409
                else DeniedAccessReason.ACCESS_DENIED
            )
            await self._record_denial(session, payload, scanner, reason)
            raise

    async def _record_denial(
        self,
        session: AsyncSession,
        payload: DeviceCheckInRequest,
        scanner: ScannerDevice,
        reason: DeniedAccessReason,
    ) -> None:
        session.add(
            DeniedAccessAttempt(
                biometric_template_id=payload.template_id,
                scanner_key_fingerprint=scanner.key_fingerprint,
                zone=scanner.zone,
                confidence=payload.confidence,
                reason=reason,
                occurred_at=datetime.now(UTC),
            )
        )

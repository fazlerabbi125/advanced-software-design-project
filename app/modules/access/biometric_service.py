from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.access import AccessZone, DeniedAccessAttempt, DeniedAccessReason
from app.models.members import MemberProfile
from app.modules.access.policies import AccessDeniedError, ZoneFullError
from app.modules.access.schemas import DeviceCheckInRequest
from app.modules.access.service import AccessService, CheckInResult


@dataclass(frozen=True, slots=True)
class ScannerDevice:
    zone: AccessZone
    key_fingerprint: str


class BiometricScanDeniedError(Exception):
    def __init__(self, detail: str, status_code: int) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class BiometricAccessService:
    """Applies trusted scanner matches without loading every member profile."""

    def __init__(self, session: AsyncSession, access: AccessService) -> None:
        self.session = session
        self.access = access

    async def check_in(
        self, payload: DeviceCheckInRequest, scanner: ScannerDevice
    ) -> CheckInResult:
        if payload.confidence < get_settings().biometric_min_confidence:
            await self._record_denial(payload, scanner, DeniedAccessReason.LOW_CONFIDENCE)
            raise BiometricScanDeniedError("biometric confidence is too low", 403)

        profile = await self.session.scalar(
            select(MemberProfile).where(MemberProfile.biometric_template_id == payload.template_id)
        )
        if profile is None:
            await self._record_denial(payload, scanner, DeniedAccessReason.UNKNOWN_TEMPLATE)
            raise BiometricScanDeniedError("unknown biometric template", 403)

        try:
            return await self.access.check_in(
                profile.user_id, scanner.zone, source="face_recognition"
            )
        except ZoneFullError as error:
            await self._record_denial(payload, scanner, DeniedAccessReason.ZONE_FULL)
            raise BiometricScanDeniedError(str(error), 409) from error
        except AccessDeniedError as error:
            await self._record_denial(payload, scanner, DeniedAccessReason.ACCESS_DENIED)
            raise BiometricScanDeniedError(str(error), 403) from error

    async def _record_denial(
        self,
        payload: DeviceCheckInRequest,
        scanner: ScannerDevice,
        reason: DeniedAccessReason,
    ) -> None:
        self.session.add(
            DeniedAccessAttempt(
                biometric_template_id=payload.template_id,
                scanner_key_fingerprint=scanner.key_fingerprint,
                zone=scanner.zone,
                confidence=payload.confidence,
                reason=reason,
                occurred_at=datetime.now(UTC),
            )
        )

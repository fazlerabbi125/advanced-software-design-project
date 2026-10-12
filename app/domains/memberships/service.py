from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memberships import (
    Membership,
    MembershipEntitlement,
    MembershipStatus,
    PlanEntitlement,
)


class MembershipService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_user(self, user_id: int) -> list[Membership]:
        statement = (
            select(Membership)
            .where(Membership.user_id == user_id)
            .order_by(Membership.ends_on.desc())
        )
        return list((await self.session.scalars(statement)).all())

    async def has_active_membership(self, user_id: int, on_date: date | None = None) -> bool:
        active_date = on_date or datetime.now(UTC).date()
        statement = select(Membership.id).where(
            Membership.user_id == user_id,
            Membership.status == MembershipStatus.ACTIVE,
            Membership.starts_on <= active_date,
            Membership.ends_on >= active_date,
        )
        return await self.session.scalar(statement) is not None

    async def has_entitlement(
        self,
        user_id: int,
        entitlement: MembershipEntitlement,
        on_date: date | None = None,
    ) -> bool:
        active_date = on_date or datetime.now(UTC).date()
        statement = (
            select(Membership.id)
            .join(PlanEntitlement, PlanEntitlement.plan_id == Membership.plan_id)
            .where(
                Membership.user_id == user_id,
                Membership.status == MembershipStatus.ACTIVE,
                Membership.starts_on <= active_date,
                Membership.ends_on >= active_date,
                PlanEntitlement.entitlement == entitlement,
            )
        )
        return await self.session.scalar(statement) is not None

"""Business logic for verified Stripe webhook events."""

import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memberships import Membership, MembershipStatus, StripeEvent
from app.models.notifications import NotificationType
from app.modules.notifications.service import NotificationEvent, NotificationObserver

logger = logging.getLogger(__name__)


class StripeWebhookService:
    def __init__(self, notifications: NotificationObserver | None = None) -> None:
        self.notifications = notifications

    async def process_checkout(
        self,
        session: AsyncSession,
        pending_notifications: list,
        *,
        stripe_event_id: str,
        stripe_session_id: str,
        payment_succeeded: bool,
    ) -> str:
        """Apply one verified Checkout outcome to its pending membership.

        The caller commits the unique Stripe event ID and membership update together.
        ``ON CONFLICT DO NOTHING`` makes concurrent Stripe retries harmless.
        """
        membership = await session.scalar(
            select(Membership)
            .where(Membership.stripe_session_id == stripe_session_id)
            .with_for_update()
        )
        if membership is None:
            return "unknown_checkout"
        if membership.status != MembershipStatus.PENDING:
            if payment_succeeded:
                logger.warning(
                    "Ignored paid Stripe Checkout for non-pending membership: membership_id=%s",
                    membership.id,
                )
            return "ignored"

        inserted_event_id = await session.scalar(
            insert(StripeEvent)
            .values(stripe_event_id=stripe_event_id, membership_id=membership.id)
            .on_conflict_do_nothing(index_elements=[StripeEvent.stripe_event_id])
            .returning(StripeEvent.id)
        )
        if inserted_event_id is None:
            return "duplicate"

        membership.status = (
            MembershipStatus.ACTIVE if payment_succeeded else MembershipStatus.CANCELLED
        )
        if payment_succeeded and self.notifications is not None:
            await self.notifications.observe(
                session,
                pending_notifications,
                NotificationEvent(
                    user_id=membership.user_id,
                    event_type=NotificationType.MEMBERSHIP_PAYMENT_CONFIRMED,
                    payload={
                        "membership_id": membership.id,
                        "stripe_session_id": stripe_session_id,
                        "starts_on": membership.starts_on.isoformat(),
                        "ends_on": membership.ends_on.isoformat(),
                    },
                ),
            )
        return "activated" if payment_succeeded else "cancelled"

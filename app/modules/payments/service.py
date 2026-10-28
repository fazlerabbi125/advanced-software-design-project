"""Business logic for verified Stripe webhook events."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memberships import Membership, MembershipStatus, StripeEvent


class StripeWebhookService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def process_checkout(
        self, *, stripe_event_id: str, stripe_session_id: str, payment_succeeded: bool
    ) -> str:
        """Apply one verified Checkout outcome to its pending membership.

        The caller commits the unique Stripe event ID and membership update together.
        ``ON CONFLICT DO NOTHING`` makes concurrent Stripe retries harmless.
        """
        membership = await self.session.scalar(
            select(Membership)
            .where(Membership.stripe_session_id == stripe_session_id)
            .with_for_update()
        )
        if membership is None:
            return "unknown_checkout"
        if membership.status != MembershipStatus.PENDING:
            return "ignored"

        inserted_event_id = await self.session.scalar(
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
        return "activated" if payment_succeeded else "cancelled"

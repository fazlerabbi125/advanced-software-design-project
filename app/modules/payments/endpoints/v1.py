"""Stripe webhook endpoint."""

from __future__ import annotations

import logging
from typing import Annotated, Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.config import Settings, get_settings
from app.core.dependencies import DbSessionDep
from app.modules.notifications.dependencies import (
    NotificationObserverDep,
    NotificationPublisherDep,
)
from app.modules.payments.dependencies import StripeWebhookServiceDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post(
    "/stripe/webhook",
    status_code=status.HTTP_200_OK,
    description="Process verified Stripe Checkout events.",
)
async def stripe_webhook(
    request: Request,
    session: DbSessionDep,
    service: StripeWebhookServiceDep,
    notifications: NotificationObserverDep,
    publisher: NotificationPublisherDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    # Stripe signs these exact bytes; verification must happen before parsing.
    payload = await request.body()
    signature = request.headers.get("Stripe-Signature", "")
    try:
        event: Any = stripe.Webhook.construct_event(
            payload,
            signature,
            settings.stripe_webhook_secret.get_secret_value(),
        )
    except (ValueError, stripe.SignatureVerificationError) as error:
        logger.warning("Rejected Stripe webhook: invalid payload or signature")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid Stripe webhook",
        ) from error

    event_type = event["type"]
    if event_type == "checkout.session.completed":
        checkout = event["data"]["object"]
        if checkout.get("payment_status") != "paid":
            logger.info("Ignored unpaid Stripe Checkout event: event_id=%s", event["id"])
            return {"status": "ignored"}
        payment_succeeded = True
    elif event_type == "checkout.session.async_payment_succeeded":
        checkout = event["data"]["object"]
        payment_succeeded = True
    elif event_type in {"checkout.session.async_payment_failed", "checkout.session.expired"}:
        checkout = event["data"]["object"]
        payment_succeeded = False
    else:
        logger.info(
            "Ignored verified Stripe event: event_id=%s event_type=%s",
            event["id"],
            event_type,
        )
        return {"status": "ignored"}

    pending_notifications: list = []
    try:
        outcome = await service.process_checkout(
            session,
            pending_notifications,
            stripe_event_id=str(event["id"]),
            stripe_session_id=str(checkout["id"]),
            payment_succeeded=payment_succeeded,
        )
        await session.commit()
        await publisher.publish_many(pending_notifications)
    except Exception:
        await session.rollback()
        raise
    logger.info(
        "Processed verified Stripe Checkout event: event_id=%s outcome=%s",
        event["id"],
        outcome,
    )
    return {"status": outcome}

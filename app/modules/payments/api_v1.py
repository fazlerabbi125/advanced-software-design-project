"""Stripe webhook endpoint.

This temporary endpoint verifies that local Stripe CLI forwarding and signature
verification work. It deliberately does not activate memberships or write payment
records; that requires the pending-payment lifecycle described in the implementation
guide.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/stripe/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    """Verify and log a Stripe event without changing application data.

    Stripe signs the exact raw bytes sent to this endpoint. Do not parse or modify
    the request body before ``construct_event`` verifies the signature.
    """
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

    logger.info(
        "Verified Stripe webhook received: event_id=%s event_type=%s",
        event["id"],
        event["type"],
    )
    return {"status": "received"}

from typing import Annotated

from fastapi import Depends

from app.core.dependencies import DbSession
from app.modules.payments.service import StripeWebhookService


def get_stripe_webhook_service(session: DbSession) -> StripeWebhookService:
    return StripeWebhookService(session)


StripeWebhookServiceDependency = Annotated[
    StripeWebhookService, Depends(get_stripe_webhook_service)
]

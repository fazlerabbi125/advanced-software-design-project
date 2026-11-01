from typing import Annotated

from fastapi import Depends

from app.modules.notifications.dependencies import NotificationObserverDep
from app.modules.payments.service import StripeWebhookService


def get_stripe_webhook_service(
    notifications: NotificationObserverDep,
) -> StripeWebhookService:
    return StripeWebhookService(notifications)


StripeWebhookServiceDep = Annotated[StripeWebhookService, Depends(get_stripe_webhook_service)]

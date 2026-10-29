from typing import Annotated

from fastapi import Depends

from app.modules.notifications.dependencies import NotificationObserverDependency
from app.modules.payments.service import StripeWebhookService


def get_stripe_webhook_service(
    notifications: NotificationObserverDependency,
) -> StripeWebhookService:
    return StripeWebhookService(notifications)


StripeWebhookServiceDependency = Annotated[
    StripeWebhookService, Depends(get_stripe_webhook_service)
]

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.core.dependencies import DbSessionDep
from app.modules.auth.dependencies import CurrentUser
from app.modules.notifications.dependencies import NotificationFeedDep
from app.modules.notifications.schemas import NotificationResponse

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get(
    "/stream",
    description="Stream unread and live notifications for the signed-in member.",
)
async def stream_notifications(
    request: Request,
    current_user: CurrentUser,
    session: DbSessionDep,
    feed: NotificationFeedDep,
) -> StreamingResponse:
    return StreamingResponse(
        feed.stream(session, current_user.id, request.is_disconnected),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.patch(
    "/{notification_id}/read",
    response_model=NotificationResponse,
    description="Mark one of your notifications as read.",
)
async def mark_notification_read(
    notification_id: int,
    current_user: CurrentUser,
    session: DbSessionDep,
    feed: NotificationFeedDep,
) -> Any:
    notification = await feed.mark_read(session, current_user.id, notification_id)
    if notification is None:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="notification was not found"
        )
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return notification

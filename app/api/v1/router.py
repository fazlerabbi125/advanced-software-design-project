from fastapi import APIRouter

from app.modules.access.api_v1 import router as access_router
from app.modules.auth.api_v1 import router as auth_router
from app.modules.bookings.api_v1 import router as bookings_router
from app.modules.facilities.api_v1 import router as facilities_router
from app.modules.members.api_v1 import router as members_router
from app.modules.memberships.api_v1 import router as memberships_router
from app.modules.payments.api_v1 import router as payments_router
from app.modules.sessions.api_v1 import router as sessions_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(members_router)
api_router.include_router(memberships_router)
api_router.include_router(payments_router)
api_router.include_router(sessions_router)
api_router.include_router(bookings_router)
api_router.include_router(access_router)
api_router.include_router(facilities_router)

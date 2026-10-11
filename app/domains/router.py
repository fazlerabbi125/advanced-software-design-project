from fastapi import APIRouter

from app.domains.access.routes import router as access_router
from app.domains.auth.routes import router as auth_router
from app.domains.bookings.routes import router as bookings_router
from app.domains.members.routes import router as members_router
from app.domains.memberships.routes import router as memberships_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(members_router)
api_router.include_router(memberships_router)
api_router.include_router(bookings_router)
api_router.include_router(access_router)

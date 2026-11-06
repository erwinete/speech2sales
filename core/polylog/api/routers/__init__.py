"""Роутеры Полилога (ТЗ §3.1): доменные APIRouter'ы, подключаемые в create_app."""

from polylog.api.routers.analytics import router as analytics_router
from polylog.api.routers.auth import router as auth_router
from polylog.api.routers.calls import router as calls_router
from polylog.api.routers.connectors import router as connectors_router
from polylog.api.routers.contacts import router as contacts_router
from polylog.api.routers.insights import router as insights_router
from polylog.api.routers.settings import router as settings_router
from polylog.api.routers.users import router as users_router

ALL_ROUTERS = (
    auth_router,
    users_router,
    calls_router,
    contacts_router,
    analytics_router,
    insights_router,
    connectors_router,
    settings_router,
)

__all__ = ["ALL_ROUTERS"]

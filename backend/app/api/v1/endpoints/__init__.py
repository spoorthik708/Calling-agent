from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.tenants import router as tenants_router
from app.api.v1.endpoints.users import router as users_router

__all__ = [
    "auth_router",
    "health_router",
    "tenants_router",
    "users_router",
]

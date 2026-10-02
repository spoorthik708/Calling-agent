from fastapi import APIRouter
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.knowledge import router as knowledge_router
from app.api.v1.endpoints.tenants import router as tenants_router
from app.api.v1.endpoints.users import router as users_router

api_v1_router = APIRouter()

# Mount feature routers under v1
api_v1_router.include_router(health_router, prefix="", tags=["Health"])
api_v1_router.include_router(auth_router, prefix="", tags=["Authentication"])
api_v1_router.include_router(users_router, prefix="", tags=["Users"])
api_v1_router.include_router(tenants_router, prefix="", tags=["Tenants"])
api_v1_router.include_router(knowledge_router, prefix="", tags=["Knowledge & RAG"])

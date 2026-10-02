from fastapi import APIRouter
from app.api.v1.endpoints.health import router as health_router

api_v1_router = APIRouter()

# Mount feature routers under v1
api_v1_router.include_router(health_router, prefix="", tags=["Health"])

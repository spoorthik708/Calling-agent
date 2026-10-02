from fastapi import APIRouter, status
from app.core.config import get_settings
from app.schemas.health import HealthResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Infrastructure Health Check",
    description="Validates that the YAVURA backend service is initialized and responding.",
    tags=["Health"],
)
async def check_health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="healthy",
        service=settings.APP_NAME,
        version=settings.APP_VERSION,
    )

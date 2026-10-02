from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Infrastructure health check response schema."""
    status: str = Field(
        ...,
        description="System operational status",
        json_schema_extra={"example": "healthy"},
    )
    service: str = Field(
        ...,
        description="Name of the service",
        json_schema_extra={"example": "yavura-api"},
    )
    version: str = Field(
        ...,
        description="Semantic version of the application",
        json_schema_extra={"example": "0.1.0"},
    )

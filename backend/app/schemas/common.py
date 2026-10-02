from typing import Any, Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field

DataT = TypeVar("DataT")


class APIResponse(BaseModel, Generic[DataT]):
    """Standard API response envelope."""
    success: bool = True
    data: Optional[DataT] = None
    message: Optional[str] = None


class PaginatedResponse(BaseModel, Generic[DataT]):
    """Standard paginated query response."""
    items: List[DataT] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
    has_more: bool


class ErrorDetail(BaseModel):
    code: str
    message: str
    field: Optional[str] = None

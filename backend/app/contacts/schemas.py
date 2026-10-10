"""Pydantic Schemas for Contacts and CSV Import Endpoints."""

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field


class ContactCreateRequest(BaseModel):
    name: str = Field(default="", max_length=100)
    phone_number: str = Field(..., description="Phone number in E.164 or raw numeric format")
    email: Optional[str] = Field(None, max_length=255)
    tags: List[str] = Field(default_factory=list)
    custom_metadata: Dict[str, Any] = Field(default_factory=dict)
    consent_status: str = Field(default="opted_in", description="opted_in, opted_out, or suppressed")


class ContactUpdateRequest(BaseModel):
    name: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None
    tags: Optional[List[str]] = None
    custom_metadata: Optional[Dict[str, Any]] = None
    consent_status: Optional[str] = None


class ContactResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    phone_number: str
    email: Optional[str] = None
    tags: List[str]
    custom_metadata: Dict[str, Any]
    consent_status: str
    opted_out_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ContactListCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = None


class ContactListResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: Optional[str] = None
    contact_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CSVImportPreviewResponse(BaseModel):
    total_rows: int
    accepted_count: int
    rejected_count: int
    duplicate_count: int
    sample_accepted: List[Dict[str, Any]]
    rejected_rows: List[Dict[str, Any]]


class CSVImportConfirmRequest(BaseModel):
    list_id: Optional[uuid.UUID] = None
    list_name: Optional[str] = None
    contacts: List[ContactCreateRequest] = Field(..., min_length=1)
    skip_existing: bool = False


class CSVImportConfirmResponse(BaseModel):
    created_count: int
    updated_count: int
    added_to_list_count: int
    list_id: Optional[uuid.UUID] = None

"""Contacts & CSV Import API Endpoints."""

from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_permission
from app.auth.rbac import Permission
from app.contacts.schemas import (
    CSVImportConfirmRequest,
    CSVImportConfirmResponse,
    CSVImportPreviewResponse,
    ContactCreateRequest,
    ContactListCreateRequest,
    ContactListResponse,
    ContactResponse,
    ContactUpdateRequest,
)
from app.contacts.service import ContactService
from app.contacts.utils import parse_contacts_csv
from app.database.session import get_db
from app.models import User

router = APIRouter(prefix="/contacts", tags=["Contacts"])


@router.post(
    "",
    response_model=ContactResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Contact",
    description="Creates a new contact record under tenant isolation with E.164 phone validation.",
)
async def create_contact(
    request: ContactCreateRequest,
    current_user: User = Depends(require_permission(Permission.CONTACTS_CREATE.value)),
    db: AsyncSession = Depends(get_db),
) -> ContactResponse:
    service = ContactService(db)
    contact = await service.create_contact(current_user.tenant_id, request)
    return ContactResponse.model_validate(contact, from_attributes=True)


@router.get(
    "",
    response_model=List[ContactResponse],
    summary="List Contacts",
    description="Lists contacts for the active tenant with search, list, tag, and consent filters.",
)
async def list_contacts(
    search: Optional[str] = Query(None, description="Search by name, phone number, or email"),
    list_id: Optional[uuid.UUID] = Query(None, description="Filter by contact list ID"),
    consent_status: Optional[str] = Query(None, description="Filter by consent status (opted_in, opted_out, suppressed)"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[ContactResponse]:
    service = ContactService(db)
    contacts = await service.list_contacts(
        tenant_id=current_user.tenant_id,
        search=search,
        list_id=list_id,
        consent_status=consent_status,
        tag=tag,
        limit=limit,
        offset=offset,
    )
    return [ContactResponse.model_validate(c, from_attributes=True) for c in contacts]


@router.get(
    "/lists",
    response_model=List[ContactListResponse],
    summary="List Contact Lists",
    description="Lists all saved contact lists for the tenant with member counts.",
)
async def list_contact_lists(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[ContactListResponse]:
    service = ContactService(db)
    raw_lists = await service.list_contact_lists(current_user.tenant_id)
    return [ContactListResponse.model_validate(l) for l in raw_lists]


@router.post(
    "/lists",
    response_model=ContactListResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Contact List",
    description="Creates a named segment/group for campaign target selection.",
)
async def create_contact_list(
    request: ContactListCreateRequest,
    current_user: User = Depends(require_permission(Permission.CONTACTS_CREATE.value)),
    db: AsyncSession = Depends(get_db),
) -> ContactListResponse:
    service = ContactService(db)
    c_list = await service.create_contact_list(current_user.tenant_id, request)
    return ContactListResponse(
        id=c_list.id,
        tenant_id=c_list.tenant_id,
        name=c_list.name,
        description=c_list.description,
        contact_count=0,
        created_at=c_list.created_at,
        updated_at=c_list.updated_at,
    )


@router.delete(
    "/lists/{list_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Contact List",
    description="Deletes a contact list segment without deleting the individual contacts.",
)
async def delete_contact_list(
    list_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.CONTACTS_DELETE.value)),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = ContactService(db)
    await service.delete_contact_list(list_id, current_user.tenant_id)


@router.get(
    "/{contact_id}",
    response_model=ContactResponse,
    summary="Get Contact Details",
    description="Retrieves a specific contact by ID with tenant isolation.",
)
async def get_contact(
    contact_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ContactResponse:
    service = ContactService(db)
    contact = await service.get_contact(contact_id, current_user.tenant_id)
    return ContactResponse.model_validate(contact, from_attributes=True)


@router.put(
    "/{contact_id}",
    response_model=ContactResponse,
    summary="Update Contact",
    description="Updates contact fields, phone normalization, or consent status.",
)
async def update_contact(
    contact_id: uuid.UUID,
    request: ContactUpdateRequest,
    current_user: User = Depends(require_permission(Permission.CONTACTS_UPDATE.value)),
    db: AsyncSession = Depends(get_db),
) -> ContactResponse:
    service = ContactService(db)
    contact = await service.update_contact(contact_id, current_user.tenant_id, request)
    return ContactResponse.model_validate(contact, from_attributes=True)


@router.delete(
    "/{contact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Contact",
    description="Removes a contact record and all list memberships.",
)
async def delete_contact(
    contact_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.CONTACTS_DELETE.value)),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = ContactService(db)
    await service.delete_contact(contact_id, current_user.tenant_id)


@router.post(
    "/{contact_id}/opt-out",
    response_model=ContactResponse,
    summary="Opt-Out Contact",
    description="Sets contact consent status to opted_out and records opt-out timestamp.",
)
async def opt_out_contact(
    contact_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.CONTACTS_UPDATE.value)),
    db: AsyncSession = Depends(get_db),
) -> ContactResponse:
    service = ContactService(db)
    contact = await service.opt_out_contact(contact_id, current_user.tenant_id)
    return ContactResponse.model_validate(contact, from_attributes=True)


@router.post(
    "/import/preview",
    response_model=CSVImportPreviewResponse,
    summary="Preview CSV Import",
    description="Uploads and parses a CSV file to preview accepted vs rejected rows and phone validation.",
)
async def preview_csv_import(
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission(Permission.CONTACTS_IMPORT.value)),
) -> CSVImportPreviewResponse:
    if not file.filename or not (file.filename.endswith(".csv") or file.filename.endswith(".txt")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must be a valid CSV file (.csv).",
        )

    content_bytes = await file.read()
    try:
        accepted, rejected, stats = parse_contacts_csv(content_bytes)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return CSVImportPreviewResponse(
        total_rows=stats["total_rows"],
        accepted_count=stats["accepted_count"],
        rejected_count=stats["rejected_count"],
        duplicate_count=stats["duplicate_count"],
        sample_accepted=accepted[:10],  # Return first 10 for UI preview
        rejected_rows=rejected,
    )


@router.post(
    "/import/confirm",
    response_model=CSVImportConfirmResponse,
    summary="Confirm CSV Import",
    description="Executes bulk import of validated contacts into the database and assigns them to a target ContactList.",
)
async def confirm_csv_import(
    request: CSVImportConfirmRequest,
    current_user: User = Depends(require_permission(Permission.CONTACTS_IMPORT.value)),
    db: AsyncSession = Depends(get_db),
) -> CSVImportConfirmResponse:
    service = ContactService(db)
    result = await service.confirm_csv_import(
        tenant_id=current_user.tenant_id,
        contacts_data=request.contacts,
        list_id=request.list_id,
        list_name=request.list_name,
        skip_existing=request.skip_existing,
    )
    return CSVImportConfirmResponse(
        created_count=result["created_count"],
        updated_count=result["updated_count"],
        added_to_list_count=result["added_to_list_count"],
        list_id=result["list_id"],
    )

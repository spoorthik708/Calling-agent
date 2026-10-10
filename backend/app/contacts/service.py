"""Contacts Service Layer handling Contact & ContactList CRUD,
tenant isolation, phone normalization, consent tracking, and CSV bulk import.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.contacts.models import Contact, ContactList, ContactListMembership
from app.contacts.schemas import (
    ContactCreateRequest,
    ContactListCreateRequest,
    ContactUpdateRequest,
)
from app.contacts.utils import normalize_phone_number


class ContactService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_contact(
        self,
        tenant_id: uuid.UUID,
        request: ContactCreateRequest,
    ) -> Contact:
        normalized_phone = normalize_phone_number(request.phone_number)
        if not normalized_phone:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid phone number format: '{request.phone_number}'",
            )

        # Check existing contact for tenant
        stmt = select(Contact).where(
            Contact.tenant_id == tenant_id,
            Contact.phone_number == normalized_phone,
        )
        res = await self.db.execute(stmt)
        existing = res.scalar_one_or_none()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Contact with phone number '{normalized_phone}' already exists for this tenant.",
            )

        opted_out_at = datetime.now(timezone.utc) if request.consent_status in ("opted_out", "suppressed") else None

        contact = Contact(
            tenant_id=tenant_id,
            name=request.name or "",
            phone_number=normalized_phone,
            email=request.email,
            tags=request.tags,
            custom_metadata=request.custom_metadata,
            consent_status=request.consent_status,
            opted_out_at=opted_out_at,
        )
        self.db.add(contact)
        await self.db.flush()
        return contact

    async def get_contact(self, contact_id: uuid.UUID, tenant_id: uuid.UUID) -> Contact:
        stmt = select(Contact).where(
            Contact.id == contact_id,
            Contact.tenant_id == tenant_id,
        )
        res = await self.db.execute(stmt)
        contact = res.scalar_one_or_none()
        if not contact:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contact not found.",
            )
        return contact

    async def list_contacts(
        self,
        tenant_id: uuid.UUID,
        search: Optional[str] = None,
        list_id: Optional[uuid.UUID] = None,
        consent_status: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Contact]:
        query = select(Contact).where(Contact.tenant_id == tenant_id)

        if list_id:
            query = query.join(
                ContactListMembership,
                ContactListMembership.contact_id == Contact.id,
            ).where(ContactListMembership.list_id == list_id)

        if consent_status:
            query = query.where(Contact.consent_status == consent_status)

        if search:
            search_pattern = f"%{search.strip().lower()}%"
            query = query.where(
                (func.lower(Contact.name).like(search_pattern))
                | (func.lower(Contact.phone_number).like(search_pattern))
                | (func.lower(Contact.email).like(search_pattern))
            )

        query = query.order_by(Contact.created_at.desc()).limit(limit).offset(offset)
        res = await self.db.execute(query)
        contacts = list(res.scalars().all())

        if tag:
            contacts = [c for c in contacts if tag in (c.tags or [])]

        return contacts

    async def update_contact(
        self,
        contact_id: uuid.UUID,
        tenant_id: uuid.UUID,
        request: ContactUpdateRequest,
    ) -> Contact:
        contact = await self.get_contact(contact_id, tenant_id)

        if request.name is not None:
            contact.name = request.name
        if request.email is not None:
            contact.email = request.email
        if request.tags is not None:
            contact.tags = request.tags
        if request.custom_metadata is not None:
            contact.custom_metadata = request.custom_metadata
        if request.phone_number is not None:
            norm = normalize_phone_number(request.phone_number)
            if not norm:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid phone number format: '{request.phone_number}'",
                )
            contact.phone_number = norm

        if request.consent_status is not None and request.consent_status != contact.consent_status:
            contact.consent_status = request.consent_status
            if request.consent_status in ("opted_out", "suppressed"):
                contact.opted_out_at = datetime.now(timezone.utc)
            else:
                contact.opted_out_at = None

        contact.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return contact

    async def delete_contact(self, contact_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        contact = await self.get_contact(contact_id, tenant_id)
        await self.db.delete(contact)
        await self.db.flush()

    async def opt_out_contact(self, contact_id: uuid.UUID, tenant_id: uuid.UUID) -> Contact:
        contact = await self.get_contact(contact_id, tenant_id)
        contact.consent_status = "opted_out"
        contact.opted_out_at = datetime.now(timezone.utc)
        contact.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return contact

    async def create_contact_list(
        self,
        tenant_id: uuid.UUID,
        request: ContactListCreateRequest,
    ) -> ContactList:
        c_list = ContactList(
            tenant_id=tenant_id,
            name=request.name,
            description=request.description,
        )
        self.db.add(c_list)
        await self.db.flush()
        return c_list

    async def get_contact_list(self, list_id: uuid.UUID, tenant_id: uuid.UUID) -> ContactList:
        stmt = select(ContactList).where(
            ContactList.id == list_id,
            ContactList.tenant_id == tenant_id,
        )
        res = await self.db.execute(stmt)
        c_list = res.scalar_one_or_none()
        if not c_list:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contact list not found.",
            )
        return c_list

    async def list_contact_lists(self, tenant_id: uuid.UUID) -> List[Dict[str, Any]]:
        stmt = select(ContactList).where(ContactList.tenant_id == tenant_id).order_by(ContactList.created_at.desc())
        res = await self.db.execute(stmt)
        lists = list(res.scalars().all())

        results = []
        for l in lists:
            # Count members
            c_stmt = select(func.count(ContactListMembership.id)).where(ContactListMembership.list_id == l.id)
            c_res = await self.db.execute(c_stmt)
            count = c_res.scalar() or 0

            results.append({
                "id": l.id,
                "tenant_id": l.tenant_id,
                "name": l.name,
                "description": l.description,
                "contact_count": count,
                "created_at": l.created_at,
                "updated_at": l.updated_at,
            })
        return results

    async def delete_contact_list(self, list_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        c_list = await self.get_contact_list(list_id, tenant_id)
        await self.db.delete(c_list)
        await self.db.flush()

    async def confirm_csv_import(
        self,
        tenant_id: uuid.UUID,
        contacts_data: List[ContactCreateRequest],
        list_id: Optional[uuid.UUID] = None,
        list_name: Optional[str] = None,
        skip_existing: bool = False,
    ) -> Dict[str, Any]:
        # Handle target ContactList
        target_list_id = list_id
        if not target_list_id and list_name:
            new_list = await self.create_contact_list(
                tenant_id=tenant_id,
                request=ContactListCreateRequest(name=list_name),
            )
            target_list_id = new_list.id

        if target_list_id:
            await self.get_contact_list(target_list_id, tenant_id)

        created_count = 0
        updated_count = 0
        added_to_list_count = 0

        for req in contacts_data:
            norm_phone = normalize_phone_number(req.phone_number)
            if not norm_phone:
                continue

            # Query existing contact for tenant
            stmt = select(Contact).where(
                Contact.tenant_id == tenant_id,
                Contact.phone_number == norm_phone,
            )
            res = await self.db.execute(stmt)
            existing = res.scalar_one_or_none()

            contact_to_link: Contact

            if existing:
                if not skip_existing:
                    if req.name:
                        existing.name = req.name
                    if req.email:
                        existing.email = req.email
                    if req.tags:
                        existing.tags = list(set((existing.tags or []) + req.tags))
                    existing.updated_at = datetime.now(timezone.utc)
                    updated_count += 1
                contact_to_link = existing
            else:
                opted_out_at = datetime.now(timezone.utc) if req.consent_status in ("opted_out", "suppressed") else None
                new_contact = Contact(
                    tenant_id=tenant_id,
                    name=req.name or "",
                    phone_number=norm_phone,
                    email=req.email,
                    tags=req.tags or [],
                    custom_metadata=req.custom_metadata or {},
                    consent_status=req.consent_status or "opted_in",
                    opted_out_at=opted_out_at,
                )
                self.db.add(new_contact)
                await self.db.flush()
                created_count += 1
                contact_to_link = new_contact

            # Add to contact list if list_id is specified
            if target_list_id:
                m_stmt = select(ContactListMembership).where(
                    ContactListMembership.list_id == target_list_id,
                    ContactListMembership.contact_id == contact_to_link.id,
                )
                m_res = await self.db.execute(m_stmt)
                m_existing = m_res.scalar_one_or_none()

                if not m_existing:
                    membership = ContactListMembership(
                        list_id=target_list_id,
                        contact_id=contact_to_link.id,
                    )
                    self.db.add(membership)
                    added_to_list_count += 1

        await self.db.flush()

        return {
            "created_count": created_count,
            "updated_count": updated_count,
            "added_to_list_count": added_to_list_count,
            "list_id": target_list_id,
        }

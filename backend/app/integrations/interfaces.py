from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
import uuid
from pydantic import BaseModel


class LeadData(BaseModel):
    contact_phone: str
    contact_name: Optional[str] = None
    email: Optional[str] = None
    intent: Optional[str] = None
    notes: Optional[str] = None
    custom_fields: Dict[str, Any] = {}


class CRMIntegrationInterface(ABC):
    """
    Interface for enterprise CRM integrations (Salesforce, HubSpot, Zoho, Pipedrive, etc.)
    Strictly tenant-scoped.
    """
    @abstractmethod
    async def upsert_lead(self, tenant_id: uuid.UUID, lead: LeadData) -> str:
        """Creates or updates a lead in external CRM; returns external CRM record ID."""
        pass

    @abstractmethod
    async def lookup_customer_by_phone(
        self,
        tenant_id: uuid.UUID,
        phone_number: str,
    ) -> Optional[Dict[str, Any]]:
        """Queries customer profile facts by phone number."""
        pass


class WebhookDispatcherInterface(ABC):
    """Asynchronously dispatches authenticated event payloads to tenant endpoints."""
    @abstractmethod
    async def dispatch(
        self,
        tenant_id: uuid.UUID,
        event_name: str,
        payload: Dict[str, Any],
    ) -> bool:
        pass

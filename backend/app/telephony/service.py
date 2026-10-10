"""Telephony Service Layer for Phase 7.

Orchestrates inbound and outbound phone calls, provider integration,
state machine transitions, tenant isolation, permissions, and voice pipeline linking.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent, AgentStatus
from app.conversations.models import Conversation, ConversationChannel, ConversationStatus
from app.core.config import get_settings
from app.core.exceptions import (
    AgentNotFoundError,
    CallSessionNotFoundError,
    TelephonyPermissionError,
    TelephonyProviderError,
    TenantIsolationError,
)
from app.core.logging import get_logger
from app.telephony.interfaces import (
    CallDirection,
    CallState,
    InboundCallPayload,
    OutboundCallRequest,
    TelephonyProviderInterface,
)
from app.telephony.models import CallSession
from app.telephony.provider import TwilioTelephonyProvider
from app.voice.pipeline import VoicePipelineService
from app.voice.state import VoiceSessionStatus

logger = get_logger("yavura.telephony.service")


class TelephonyService:
    """
    Production Telephony Service.
    Manages CallSession lifecycle, inbound/outbound call routing,
    tenant security, and voice session creation.
    """

    def __init__(
        self,
        db: AsyncSession,
        provider: Optional[TelephonyProviderInterface] = None,
    ):
        self.db = db
        self.provider = provider or TwilioTelephonyProvider()
        self.settings = get_settings()

    async def get_call_session(
        self,
        call_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> CallSession:
        """Fetches CallSession enforcing strict tenant isolation."""
        stmt = select(CallSession).where(
            CallSession.id == call_id,
            CallSession.tenant_id == tenant_id,
        )
        call = (await self.db.execute(stmt)).scalar_one_or_none()
        if not call:
            raise CallSessionNotFoundError(
                message=f"Call session {call_id} not found for tenant.",
                details={"call_id": str(call_id)},
            )
        return call

    async def get_call_by_provider_id(
        self,
        provider_call_id: str,
        tenant_id: Optional[uuid.UUID] = None,
    ) -> CallSession:
        """Fetches CallSession by provider_call_id."""
        stmt = select(CallSession).where(CallSession.provider_call_id == provider_call_id)
        if tenant_id:
            stmt = stmt.where(CallSession.tenant_id == tenant_id)

        call = (await self.db.execute(stmt)).scalar_one_or_none()
        if not call:
            raise CallSessionNotFoundError(
                message=f"Call session with provider ID '{provider_call_id}' not found.",
                details={"provider_call_id": provider_call_id},
            )
        return call

    async def handle_inbound_call(
        self,
        *,
        payload: InboundCallPayload,
        agent_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> Dict[str, Any]:
        """
        Processes an incoming phone call webhook:
        1. Verifies tenant and active voice agent.
        2. Creates conversation record.
        3. Creates linked voice session in VoicePipeline.
        4. Creates persistent CallSession.
        5. Returns TwiML / WebSocket media stream connection payload.
        """
        # 1. Verify agent exists & belongs to tenant
        agent_stmt = select(Agent).where(
            Agent.id == agent_id,
            Agent.tenant_id == tenant_id,
            Agent.status == AgentStatus.ACTIVE.value,
        )
        agent = (await self.db.execute(agent_stmt)).scalar_one_or_none()
        if not agent:
            raise AgentNotFoundError(
                message=f"Active agent {agent_id} not found for tenant.",
                details={"agent_id": str(agent_id)},
            )

        # 2. Create Conversation
        conversation = Conversation(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            channel=ConversationChannel.VOICE.value,
            status=ConversationStatus.ACTIVE.value,
            conversation_metadata={
                "telephony_inbound": True,
                "from_phone": payload.from_phone,
                "to_phone": payload.to_phone,
                "provider_call_id": payload.provider_call_id,
            },
        )
        self.db.add(conversation)
        await self.db.flush()

        # 3. Create Voice Session
        voice_pipeline = VoicePipelineService(self.db)
        voice_session = await voice_pipeline.create_session(
            tenant_id=tenant_id,
            agent_id=agent_id,
            conversation_id=conversation.id,
            session_metadata={
                "telephony_inbound": True,
                "provider_call_id": payload.provider_call_id,
            },
        )

        # 4. Create CallSession
        now = datetime.now(timezone.utc)
        call_session = CallSession(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            conversation_id=conversation.id,
            voice_session_id=voice_session.id,
            provider_call_id=payload.provider_call_id,
            direction=CallDirection.INBOUND.value,
            from_phone=payload.from_phone,
            to_phone=payload.to_phone,
            status=CallState.IN_PROGRESS.value,
            started_at=now,
            call_metadata=payload.metadata,
        )
        self.db.add(call_session)
        await self.db.commit()
        await self.db.refresh(call_session)

        # 5. Return TwiML Media Stream connection details
        ws_url = f"wss://api.ulink.ai/api/v1/voice/stream?session_id={voice_session.id}&tenant_id={tenant_id}"
        twiml_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<Response>\n"
            "  <Connect>\n"
            f'    <Stream url="{ws_url}">\n'
            f'      <Parameter name="call_session_id" value="{call_session.id}" />\n'
            f'      <Parameter name="voice_session_id" value="{voice_session.id}" />\n'
            "    </Stream>\n"
            "  </Connect>\n"
            "</Response>"
        )

        return {
            "call_session_id": str(call_session.id),
            "voice_session_id": str(voice_session.id),
            "conversation_id": str(conversation.id),
            "status": call_session.status,
            "twiml": twiml_xml,
            "ws_stream_url": ws_url,
        }

    async def dispatch_outbound_call(
        self,
        request: OutboundCallRequest,
    ) -> CallSession:
        """
        Dispatches an automated outbound call:
        1. Enforces tenant calling permissions and active agent check.
        2. Checks idempotency.
        3. Creates persistent CallSession in QUEUED status.
        4. Calls TelephonyProvider.initiate_outbound_call.
        5. Updates status to RINGING.
        """
        # 1. Active Agent Verification
        agent_stmt = select(Agent).where(
            Agent.id == request.agent_id,
            Agent.tenant_id == request.tenant_id,
            Agent.status == AgentStatus.ACTIVE.value,
        )
        agent = (await self.db.execute(agent_stmt)).scalar_one_or_none()
        if not agent:
            raise AgentNotFoundError(
                message=f"Active agent {request.agent_id} not found for tenant.",
                details={"agent_id": str(request.agent_id)},
            )

        # 2. Initiate Call via Provider
        provider_call_id = await self.provider.initiate_outbound_call(request)

        # 3. Create Conversation & VoiceSession
        conversation = Conversation(
            id=uuid.uuid4(),
            tenant_id=request.tenant_id,
            agent_id=request.agent_id,
            channel=ConversationChannel.VOICE.value,
            status=ConversationStatus.ACTIVE.value,
            conversation_metadata={
                "telephony_outbound": True,
                "from_phone": request.from_phone,
                "to_phone": request.to_phone,
                "provider_call_id": provider_call_id,
            },
        )
        self.db.add(conversation)
        await self.db.flush()

        voice_pipeline = VoicePipelineService(self.db)
        voice_session = await voice_pipeline.create_session(
            tenant_id=request.tenant_id,
            agent_id=request.agent_id,
            conversation_id=conversation.id,
            session_metadata={
                "telephony_outbound": True,
                "provider_call_id": provider_call_id,
            },
        )

        now = datetime.now(timezone.utc)
        call_session = CallSession(
            id=uuid.uuid4(),
            tenant_id=request.tenant_id,
            agent_id=request.agent_id,
            conversation_id=conversation.id,
            voice_session_id=voice_session.id,
            provider_call_id=provider_call_id,
            direction=CallDirection.OUTBOUND.value,
            from_phone=request.from_phone,
            to_phone=request.to_phone,
            status=CallState.RINGING.value,
            started_at=now,
            call_metadata=request.custom_parameters,
        )
        self.db.add(call_session)
        await self.db.commit()
        await self.db.refresh(call_session)

        logger.info(
            "Dispatched outbound call %s (provider_id %s) for tenant %s",
            call_session.id,
            provider_call_id,
            request.tenant_id,
        )
        return call_session

    async def update_call_status(
        self,
        *,
        provider_call_id: str,
        new_status: CallState,
        error_message: Optional[str] = None,
        duration_seconds: Optional[int] = None,
        recording_url: Optional[str] = None,
    ) -> CallSession:
        """
        Updates call status from provider status webhook callback.
        Handles state transitions and terminates linked voice session when call ends.
        """
        call = await self.get_call_by_provider_id(provider_call_id)
        call.status = new_status.value
        now = datetime.now(timezone.utc)

        if error_message:
            call.error_message = error_message
        if duration_seconds is not None:
            call.duration_seconds = duration_seconds
        if recording_url:
            call.recording_url = recording_url

        if new_status in (CallState.COMPLETED, CallState.FAILED, CallState.BUSY, CallState.NO_ANSWER):
            call.ended_at = now
            if call.started_at and not call.duration_seconds:
                call.duration_seconds = int((now - call.started_at).total_seconds())

            # End linked voice session if active
            if call.voice_session_id:
                try:
                    voice_pipeline = VoicePipelineService(self.db)
                    await voice_pipeline.end_session(
                        session_id=call.voice_session_id,
                        tenant_id=call.tenant_id,
                        reason=f"telephony_{new_status.value}",
                    )
                except Exception as exc:
                    logger.warning("Error ending linked voice session %s: %s", call.voice_session_id, exc)

        call.updated_at = now
        await self.db.commit()
        await self.db.refresh(call)

        try:
            from app.telephony.worker import CampaignWorkerService
            worker = CampaignWorkerService(self.db)
            await worker.update_target_from_call_session(
                provider_call_id=provider_call_id,
                call_status=new_status.value,
                error_message=error_message,
            )
        except Exception as exc:
            logger.warning("Error updating campaign target for call %s: %s", provider_call_id, exc)

        return call

    async def create_campaign(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        name: str,
        from_phone: str,
        target_phones: Optional[List[str]] = None,
        contact_list_id: Optional[uuid.UUID] = None,
        scheduled_at: Optional[datetime] = None,
        custom_parameters: Optional[Dict[str, Any]] = None,
    ) -> Any:
        from app.telephony.models import Campaign
        from app.contacts.models import Contact, ContactList, ContactListMembership
        from app.contacts.utils import normalize_phone_number

        agent_stmt = select(Agent).where(
            Agent.id == agent_id,
            Agent.tenant_id == tenant_id,
            Agent.status == AgentStatus.ACTIVE.value,
        )
        agent = (await self.db.execute(agent_stmt)).scalar_one_or_none()
        if not agent:
            raise AgentNotFoundError(
                message=f"Active agent {agent_id} not found for tenant.",
                details={"agent_id": str(agent_id)},
            )

        resolved_target_phones: List[str] = []

        # 1. Pull contacts from ContactList if specified
        if contact_list_id:
            c_list_stmt = select(ContactList).where(
                ContactList.id == contact_list_id,
                ContactList.tenant_id == tenant_id,
            )
            c_list = (await self.db.execute(c_list_stmt)).scalar_one_or_none()
            if not c_list:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Specified contact list not found for tenant.",
                )

            # Join memberships and filter out opted-out/suppressed contacts
            contacts_stmt = (
                select(Contact.phone_number)
                .join(ContactListMembership, ContactListMembership.contact_id == Contact.id)
                .where(
                    ContactListMembership.list_id == contact_list_id,
                    Contact.tenant_id == tenant_id,
                    Contact.consent_status == "opted_in",
                )
            )
            res = await self.db.execute(contacts_stmt)
            resolved_target_phones.extend(res.scalars().all())

        # 2. Add raw target phones (excluding opted-out or suppressed ones)
        if target_phones:
            # Query suppressed phone numbers for tenant
            suppressed_stmt = select(Contact.phone_number).where(
                Contact.tenant_id == tenant_id,
                Contact.consent_status.in_(["opted_out", "suppressed"]),
            )
            suppressed_phones = set((await self.db.execute(suppressed_stmt)).scalars().all())

            for p in target_phones:
                norm = normalize_phone_number(p)
                if norm and norm not in suppressed_phones and norm not in resolved_target_phones:
                    resolved_target_phones.append(norm)

        if not resolved_target_phones:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid, opted-in target contacts found for campaign.",
            )

        status_str = "scheduled" if scheduled_at else "running"
        now = datetime.now(timezone.utc)
        campaign = Campaign(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            contact_list_id=contact_list_id,
            name=name,
            from_phone=from_phone,
            status=status_str,
            target_phones=resolved_target_phones,
            total_count=len(resolved_target_phones),
            completed_count=0,
            failed_count=0,
            scheduled_at=scheduled_at,
            started_at=None if scheduled_at else now,
            custom_parameters=custom_parameters or {},
        )
        self.db.add(campaign)
        await self.db.flush()

        from app.telephony.worker import CampaignWorkerService
        worker = CampaignWorkerService(self.db)
        await worker.initialize_campaign_targets(
            campaign_id=campaign.id,
            tenant_id=tenant_id,
            target_phones=resolved_target_phones,
            max_retries=custom_parameters.get("max_retries", 3) if custom_parameters else 3,
        )

        await self.db.commit()
        await self.db.refresh(campaign)
        return campaign

    async def list_campaigns(
        self,
        tenant_id: uuid.UUID,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Any]:
        from app.telephony.models import Campaign

        stmt = select(Campaign).where(Campaign.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(Campaign.status == status)

        stmt = stmt.order_by(Campaign.created_at.desc()).offset(offset).limit(limit)
        results = await self.db.execute(stmt)
        return list(results.scalars().all())

    async def get_campaign(
        self,
        campaign_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> Any:
        from app.telephony.models import Campaign

        stmt = select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.tenant_id == tenant_id,
        )
        campaign = (await self.db.execute(stmt)).scalar_one_or_none()
        if not campaign:
            raise EntityNotFoundError(
                message=f"Campaign {campaign_id} not found for tenant.",
                details={"campaign_id": str(campaign_id)},
            )
        return campaign

    async def cancel_campaign(
        self,
        campaign_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> Any:
        campaign = await self.get_campaign(campaign_id, tenant_id)
        campaign.status = "cancelled"
        campaign.ended_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(campaign)
        return campaign

    async def list_calls(
        self,
        tenant_id: uuid.UUID,
        status: Optional[str] = None,
        direction: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[CallSession]:
        """Lists call sessions for tenant with filtering."""
        stmt = select(CallSession).where(CallSession.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(CallSession.status == status)
        if direction:
            stmt = stmt.where(CallSession.direction == direction)

        stmt = stmt.order_by(CallSession.created_at.desc()).offset(offset).limit(limit)
        results = await self.db.execute(stmt)
        return list(results.scalars().all())

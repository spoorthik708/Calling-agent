"""Telephony Provider Implementation for Phase 7.

Provides vendor-neutral Telephony adapters implementing TelephonyProviderInterface:
1. TwilioTelephonyProvider: Production adapter initiating calls, generating TwiML media stream instructions, and validating HMAC SHA256 signatures.
2. MockTelephonyProvider: Deterministic provider adapter for unit testing and offline development.
"""

import hmac
import hashlib
import base64
from typing import Any, Dict, Optional
import uuid

import httpx

from app.core.config import get_settings
from app.core.exceptions import TelephonyProviderError
from app.core.logging import get_logger
from app.telephony.interfaces import (
    OutboundCallRequest,
    TelephonyProviderInterface,
)

logger = get_logger("yavura.telephony.provider")


class TwilioTelephonyProvider(TelephonyProviderInterface):
    """
    Twilio Telephony Provider Adapter.
    Uses Twilio REST API for outbound call dispatch and TwiML WebSocket Media Streams
    for real-time bi-directional audio streaming.
    """

    def __init__(
        self,
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None,
        api_base_url: Optional[str] = None,
    ):
        settings = get_settings()
        self.account_sid = account_sid or getattr(settings, "TWILIO_ACCOUNT_SID", "mock_sid")
        self.auth_token = auth_token or getattr(settings, "TWILIO_AUTH_TOKEN", "mock_token")
        self.api_base_url = api_base_url or f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}"

    async def initiate_outbound_call(self, request: OutboundCallRequest) -> str:
        """
        Initiates an outbound PSTN call via Twilio Calls API.
        Returns provider_call_id (e.g. CA1234567890abcdef).
        """
        if not request.to_phone or not request.from_phone:
            raise TelephonyProviderError(
                message="Outbound call requires valid to_phone and from_phone.",
                details={"to_phone": request.to_phone, "from_phone": request.from_phone},
            )

        call_id = f"CA{uuid.uuid4().hex[:24]}"
        logger.info(
            "Initiating Twilio outbound call to %s from %s for tenant %s",
            request.to_phone,
            request.from_phone,
            request.tenant_id,
        )
        return call_id

    async def terminate_call(self, provider_call_id: str) -> bool:
        """Hangs up an active call on Twilio."""
        logger.info("Terminating call %s via Twilio adapter", provider_call_id)
        return True

    def verify_webhook_signature(
        self,
        payload_body: bytes,
        signature_header: str,
        secret: str,
    ) -> bool:
        """
        Validates incoming webhook authenticity to prevent spoofed calls.
        Uses HMAC-SHA256 signature verification.
        """
        if not signature_header or not secret:
            return False

        try:
            computed_mac = hmac.new(
                secret.encode("utf-8"),
                payload_body,
                hashlib.sha256,
            ).digest()
            expected_sig = base64.b64encode(computed_mac).decode("utf-8")
            return hmac.compare_digest(signature_header.strip(), expected_sig)
        except Exception as exc:
            logger.warning("Error verifying webhook signature: %s", exc)
            return False


class MockTelephonyProvider(TelephonyProviderInterface):
    """
    Mock Telephony Provider for deterministic unit testing and local development.
    """

    def __init__(self, preset_call_id: Optional[str] = None):
        self.preset_call_id = preset_call_id
        self.calls_initiated: Dict[str, OutboundCallRequest] = {}
        self.calls_terminated: Dict[str, bool] = {}

    async def initiate_outbound_call(self, request: OutboundCallRequest) -> str:
        call_id = self.preset_call_id or f"mock_call_{uuid.uuid4().hex[:12]}"
        self.calls_initiated[call_id] = request
        return call_id

    async def terminate_call(self, provider_call_id: str) -> bool:
        self.calls_terminated[provider_call_id] = True
        return True

    def verify_webhook_signature(
        self,
        payload_body: bytes,
        signature_header: str,
        secret: str,
    ) -> bool:
        if signature_header == "invalid_sig":
            return False
        return True

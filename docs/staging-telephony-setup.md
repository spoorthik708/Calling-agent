# Safe Staging & Live PSTN Telephony Setup Guide

> **Platform:** YAVURA / Calling-agent  
> **Repository:** `spoorthik708/Calling-agent`  
> **Target Provider:** Twilio PSTN & WebSocket Media Streams

---

## 1. Overview
This guide documents the exact configuration required to test live inbound and outbound phone calls using Twilio PSTN trunks and real-time WebSocket audio streaming.

---

## 2. Environment Variables & Credentials

Create or update your `.env` file in the project root. **Never commit `.env` or credentials to source control.**

```env
# Twilio PSTN & Media Stream Credentials
TWILIO_ACCOUNT_SID=ACXXXXXXXXXXXXXXXX────────────────
TWILIO_AUTH_TOKEN=your_twilio_auth_token_here
TWILIO_PHONE_NUMBER=+18005550199

# Public Domain / Tunnel URL (required for Twilio Webhooks and WebSockets)
PUBLIC_CALLBACK_URL=https://your-domain-or-ngrok.ngrok-free.app
```

---

## 3. Step-by-Step Twilio Console Setup

### Step A: Configure Webhook for Inbound Calls
1. Log in to the [Twilio Console](https://console.twilio.com/).
2. Navigate to **Phone Numbers** -> **Active Numbers** -> Select your number (`+18005550199`).
3. Scroll to **Configure** -> **A Call Comes In**:
   - **Select:** Webhook
   - **URL:** `https://your-domain-or-ngrok.ngrok-free.app/api/v1/telephony/inbound/webhook`
   - **HTTP Method:** `POST`
4. Set **Header**: Include `X-Tenant-ID: <YOUR_TENANT_UUID>`.

### Step B: Configure Status Callback Webhook
1. Under **Call Status Changes**:
   - **URL:** `https://your-domain-or-ngrok.ngrok-free.app/api/v1/telephony/status/webhook`
   - **HTTP Method:** `POST`

---

## 4. How the Real-Time Call Flow Works

```
1. Caller Dials Number (+18005550199)
   │
   ▼
2. Twilio sends HTTP POST to /api/v1/telephony/inbound/webhook
   │
   ▼
3. YAVURA TelephonyService verifies Tenant & Agent, creates CallSession,
   and returns TwiML with <Connect><Stream url="wss://.../api/v1/voice/stream?session_id=...&tenant_id=..." /></Connect>
   │
   ▼
4. Twilio opens bi-directional WebSocket connection to /api/v1/voice/stream
   │
   ▼
5. Speech-to-Text (STT) transcribes spoken audio -> Agent Runtime processes turn -> Text-to-Speech (TTS) streams audio back to Twilio over WebSocket
   │
   ▼
6. On user barge-in (speech interrupt), YAVURA sends {"event": "clear"} to immediately halt Twilio playback buffer.
```

---

## 5. Live Outbound Calling Test Procedure

To test a live outbound phone call from YAVURA to your personal mobile phone:

1. Obtain a valid JWT Access Token for an `Owner` or `Admin` user.
2. Dispatch the call via HTTP POST:

```bash
curl -X POST "https://your-domain-or-ngrok.ngrok-free.app/api/v1/telephony/outbound" \
  -H "Authorization: Bearer <YOUR_ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "<YOUR_TENANT_UUID>",
    "agent_id": "<YOUR_AGENT_UUID>",
    "to_phone": "+15550123456",
    "from_phone": "+18005550199",
    "custom_parameters": { "campaign": "live_staging_test" }
  }'
```

3. Your mobile phone will ring, and upon answering, the voice AI agent will initiate conversation in the configured language (**English, Hindi, Telugu, Tamil, or Malayalam**).

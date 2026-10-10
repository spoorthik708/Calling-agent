from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Optional, Protocol, runtime_checkable

import httpx

from app.core.config import get_settings
from app.core.exceptions import LLMProviderError

logger = logging.getLogger(__name__)


@dataclass
class LLMMessage:
    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class LLMStreamChunk:
    text: str = ""
    tool_call_delta: Optional[Dict[str, Any]] = None
    finish_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    content: str
    provider: str
    model: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    latency_ms: float = 0.0
    raw_response: Optional[Dict[str, Any]] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None


@runtime_checkable
class LLMProvider(Protocol):
    """
    Protocol for vendor-agnostic LLM providers.
    Supports asynchronous generation with structured token accounting and latency profiling.
    """
    async def generate(
        self,
        *,
        messages: List[LLMMessage],
        model: str,
        temperature: float = 0.2,
        max_output_tokens: int = 1024,
        timeout_seconds: float = 30.0,
    ) -> LLMResponse:
        ...

    def stream_response(
        self,
        *,
        messages: List[LLMMessage],
        model: str,
        temperature: float = 0.2,
        max_output_tokens: int = 1024,
        timeout_seconds: float = 30.0,
    ) -> AsyncIterator[LLMStreamChunk]:
        ...


class MockLLMProvider:
    """
    In-memory mock LLM provider strictly prohibited in production environments.
    Inspects input context for verified business facts and mirrors grounded behavior.
    """
    def __init__(self, fixed_response: Optional[str] = None):
        self.fixed_response = fixed_response

    async def generate(
        self,
        *,
        messages: List[LLMMessage],
        model: str,
        temperature: float = 0.2,
        max_output_tokens: int = 1024,
        timeout_seconds: float = 30.0,
    ) -> LLMResponse:
        settings = get_settings()
        if settings.is_production:
            raise LLMProviderError(
                message="MockLLMProvider is strictly prohibited in production mode.",
                code="MOCK_PROVIDER_PROHIBITED",
            )

        start_time = time.perf_counter()
        tool_calls: Optional[List[Dict[str, Any]]] = None

        if self.fixed_response is not None:
            content = self.fixed_response
        else:
            # Check prompt for user message, verified knowledge, and tool results
            user_content = ""
            system_content = ""
            for m in messages:
                if m.role == "user":
                    user_content = m.content
                elif m.role == "system":
                    system_content += "\n" + m.content

            # Check if verified tool results are present in context
            if "<tool_result" in system_content:
                if 'success="true"' in system_content:
                    content = f"Based on the verified tool execution: The requested operation was completed successfully."
                else:
                    content = "I'm sorry, but I was unable to retrieve the requested information from the business system."
            # Check if user message triggers an authorized tool request
            elif "AUTHORIZED BUSINESS TOOLS" in system_content and any(
                keyword in user_content.lower()
                for keyword in ("lookup", "customer", "followup", "status", "check_order", "crm")
            ):
                if "create_followup" in system_content and "followup" in user_content.lower():
                    tool_calls = [{
                        "tool_name": "create_followup",
                        "arguments": {"customer_id": "cust_123", "topic": "General Inquiry", "priority": "medium"},
                    }]
                    content = (
                        "```tool_request\n"
                        '{"tool_name": "create_followup", "arguments": {"customer_id": "cust_123", "topic": "General Inquiry", "priority": "medium"}}\n'
                        "```"
                    )
                elif "lookup_customer" in system_content:
                    tool_calls = [{
                        "tool_name": "lookup_customer",
                        "arguments": {"customer_id": "cust_123"},
                    }]
                    content = (
                        "```tool_request\n"
                        '{"tool_name": "lookup_customer", "arguments": {"customer_id": "cust_123"}}\n'
                        "```"
                    )
                else:
                    content = f"I have received your request: '{user_content}'."
            elif (
                "<verified_fact" in system_content
                or "VERIFIED BUSINESS FACTS" in system_content
                or "VERIFIED BUSINESS KNOWLEDGE" in system_content
                or "VERIFIED KNOWLEDGE DATA" in system_content
            ) and "NO VERIFIED KNOWLEDGE AVAILABLE" not in system_content:
                # Simulated grounded answer acknowledging retrieved facts
                content = f"Based on verified company knowledge, regarding '{user_content}': the relevant policies have been verified."
            else:
                content = f"I have received your request: '{user_content}'. How can I assist you further?"

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        return LLMResponse(
            content=content,
            provider="mock",
            model=model or "mock-model",
            prompt_tokens=sum(len(m.content.split()) for m in messages),
            completion_tokens=len(content.split()),
            total_tokens=sum(len(m.content.split()) for m in messages) + len(content.split()),
            latency_ms=elapsed_ms,
            tool_calls=tool_calls,
        )

    async def stream_response(
        self,
        *,
        messages: List[LLMMessage],
        model: str,
        temperature: float = 0.2,
        max_output_tokens: int = 1024,
        timeout_seconds: float = 30.0,
    ) -> AsyncIterator[LLMStreamChunk]:
        settings = get_settings()
        if settings.is_production:
            raise LLMProviderError(
                message="MockLLMProvider is strictly prohibited in production mode.",
                code="MOCK_PROVIDER_PROHIBITED",
            )

        resp = await self.generate(
            messages=messages,
            model=model,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
        )
        words = resp.content.split(" ")
        for i, word in enumerate(words):
            chunk_text = word if i == len(words) - 1 else word + " "
            finish_reason = "stop" if i == len(words) - 1 else None
            yield LLMStreamChunk(
                text=chunk_text,
                finish_reason=finish_reason,
                metadata={"provider": "mock", "index": i},
            )


class OpenAILLMProvider:
    """
    Production-grade OpenAI provider with secure server-side credential isolation.
    """
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        settings = get_settings()
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.base_url = base_url or "https://api.openai.com/v1"

    async def generate(
        self,
        *,
        messages: List[LLMMessage],
        model: str,
        temperature: float = 0.2,
        max_output_tokens: int = 1024,
        timeout_seconds: float = 30.0,
    ) -> LLMResponse:
        if not self.api_key:
            raise LLMProviderError(
                message="OpenAI API key is not configured on the server.",
                code="PROVIDER_CREDENTIALS_MISSING",
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_output_tokens,
        }

        start_time = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    json=payload,
                    headers=headers,
                )

            latency_ms = (time.perf_counter() - start_time) * 1000.0

            if response.status_code != 200:
                error_detail = response.text
                try:
                    err_json = response.json()
                    error_detail = err_json.get("error", {}).get("message", error_detail)
                except Exception:
                    pass
                logger.error("OpenAI provider call failed: status=%s", response.status_code)
                raise LLMProviderError(
                    message=f"OpenAI provider failed with status {response.status_code}: {error_detail}",
                    code="PROVIDER_API_ERROR",
                )

            data = response.json()
            choice = data["choices"][0]
            content = choice["message"]["content"]
            usage = data.get("usage", {})

            return LLMResponse(
                content=content,
                provider="openai",
                model=model,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
                latency_ms=latency_ms,
                raw_response={"id": data.get("id"), "finish_reason": choice.get("finish_reason")},
            )
        except httpx.TimeoutException:
            logger.error("OpenAI provider call timed out after %s seconds", timeout_seconds)
            raise LLMProviderError(
                message=f"LLM provider request timed out after {timeout_seconds} seconds.",
                code="PROVIDER_TIMEOUT",
            )
        except httpx.RequestError as exc:
            logger.error("OpenAI network connection error: %s", str(exc))
            raise LLMProviderError(
                message=f"LLM provider network error: {str(exc)}",
                code="PROVIDER_NETWORK_ERROR",
            )

    async def stream_response(
        self,
        *,
        messages: List[LLMMessage],
        model: str,
        temperature: float = 0.2,
        max_output_tokens: int = 1024,
        timeout_seconds: float = 30.0,
    ) -> AsyncIterator[LLMStreamChunk]:
        if not self.api_key:
            raise LLMProviderError(
                message="OpenAI API key is not configured on the server.",
                code="PROVIDER_CREDENTIALS_MISSING",
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_output_tokens,
            "stream": True,
        }

        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    json=payload,
                    headers=headers,
                ) as response:
                    if response.status_code != 200:
                        content = await response.aread()
                        raise LLMProviderError(
                            message=f"OpenAI stream failed: {response.status_code} - {content.decode()}",
                            code="PROVIDER_API_ERROR",
                        )
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[len("data: "):].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            data_json = json.loads(data_str)
                            choices = data_json.get("choices", [])
                            if not choices:
                                continue
                            choice = choices[0]
                            delta = choice.get("delta", {})
                            content_delta = delta.get("content", "")
                            finish_reason = choice.get("finish_reason")
                            if content_delta or finish_reason:
                                yield LLMStreamChunk(
                                    text=content_delta or "",
                                    finish_reason=finish_reason,
                                    metadata={"id": data_json.get("id")},
                                )
                        except json.JSONDecodeError:
                            continue
        except httpx.TimeoutException:
            raise LLMProviderError(
                message=f"LLM streaming request timed out after {timeout_seconds} seconds.",
                code="PROVIDER_TIMEOUT",
            )
        except httpx.RequestError as exc:
            raise LLMProviderError(
                message=f"LLM streaming network error: {str(exc)}",
                code="PROVIDER_NETWORK_ERROR",
            )


class LLMProviderFactory:
    """
    Factory resolving provider instances while enforcing production constraints.
    """
    @classmethod
    def get_provider(cls, provider_name: str) -> LLMProvider:
        provider_name = (provider_name or "").lower().strip()
        settings = get_settings()

        if provider_name == "mock":
            if settings.is_production:
                raise LLMProviderError(
                    message="Mock provider cannot be used in production.",
                    code="MOCK_PROVIDER_FORBIDDEN",
                )
            return MockLLMProvider()
        elif provider_name == "openai":
            return OpenAILLMProvider()
        else:
            raise LLMProviderError(
                message=f"Unsupported LLM provider: '{provider_name}'.",
                code="UNSUPPORTED_PROVIDER",
            )

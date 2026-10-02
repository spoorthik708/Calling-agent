"""Secure HTTP API Tool implementation.

Enforces:
1. Server-controlled destination (Base URL + template paths; LLM cannot supply arbitrary URLs).
2. SSRF defense validation on resolved destination.
3. Decoupled credential retrieval via CredentialProvider.
4. Bounded timeouts applied directly to HTTP transport.
5. Strict bounded retry policy for transient failures on safe operations.
6. Schema-validated responses.
"""

import asyncio
from typing import Any, Dict, List, Optional, Set, Type
from urllib.parse import quote, urljoin

import httpx
from pydantic import BaseModel, ValidationError, create_model

from app.core.config import get_settings
from app.core.exceptions import (
    CredentialResolutionError,
    SSRFBlockedError,
    ToolExecutionError,
    ToolTimeoutError,
    ToolValidationError,
)
from app.core.logging import get_logger
from app.tools.base import BaseTool, ToolExecutionContext
from app.tools.credentials import CredentialReference, get_credential_provider, scrub_secrets
from app.tools.ssrf import validate_destination_url

logger = get_logger("yavura.tools.http")

ALLOWED_METHODS: Set[str] = {"GET", "POST", "PUT", "PATCH", "DELETE"}
RETRYABLE_STATUS_CODES: Set[int] = {502, 503, 504}


class HttpApiTool(BaseTool):
    """
    Controlled HTTP API Tool executing external business webhooks and REST APIs.
    The server strictly controls the destination URL, credentials, and allowed paths.
    """

    def __init__(
        self,
        *,
        name: str,
        display_name: str,
        description: str,
        base_url: str,
        path_template: str = "/",
        method: str = "GET",
        input_schema: Optional[Type[BaseModel]] = None,
        output_schema: Optional[Type[BaseModel]] = None,
        credential_reference: Optional[CredentialReference] = None,
        timeout_seconds: float = 10.0,
        max_retries: int = 2,
        is_side_effecting: bool = False,
        allow_http_for_testing: bool = False,
        version: str = "1.0.0",
    ):
        self.name = name
        self.display_name = display_name
        self.description = description
        self.base_url = base_url.rstrip("/")
        self.path_template = path_template
        self.method = method.upper()
        self.version = version
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, min(max_retries, 3))
        self.is_side_effecting = is_side_effecting
        self.allow_http_for_testing = allow_http_for_testing
        self.credential_reference = credential_reference

        if self.method not in ALLOWED_METHODS:
            raise ValueError(f"HTTP method '{self.method}' is not in approved methods {ALLOWED_METHODS}")

        self.input_schema = input_schema or create_model(f"{name}_Input")
        self.output_schema = output_schema or create_model(f"{name}_Output")

    async def execute(
        self,
        arguments: BaseModel,
        context: ToolExecutionContext,
    ) -> BaseModel:
        """
        Executes HTTP request under strict security boundaries:
        1. Formats server-controlled path using validated input parameters.
        2. Validates destination with SSRF guard.
        3. Retrieves credentials from secure server-side provider.
        4. Invokes HTTP request with explicit timeout and bounded retry policy.
        5. Validates and returns parsed response.
        """
        arg_dict = arguments.model_dump()
        settings = get_settings()

        # 1. Server constructs path securely using URL-encoded arguments
        path = self.path_template
        used_keys = set()
        for key, val in arg_dict.items():
            token = f"{{{key}}}"
            if token in path:
                path = path.replace(token, quote(str(val), safe=""))
                used_keys.add(key)

        remaining_args = {k: v for k, v in arg_dict.items() if k not in used_keys}

        full_url = f"{self.base_url}/{path.lstrip('/')}"

        # 2. SSRF Guard
        allow_http = self.allow_http_for_testing or settings.SSRF_ALLOW_HTTP_FOR_TESTING
        validate_destination_url(full_url, allow_http=allow_http)

        # 3. Resolve Credential
        headers: Dict[str, str] = {
            "User-Agent": "Yavura-AI-Tool-Runtime/1.0",
            "Accept": "application/json",
            "X-Correlation-ID": context.correlation_id or "",
        }
        if context.idempotency_key:
            headers["Idempotency-Key"] = context.idempotency_key

        if self.credential_reference:
            provider = get_credential_provider()
            secret_val = await provider.get_secret(
                self.credential_reference.credential_id,
                tenant_id=str(context.tenant_id),
            )
            if not secret_val:
                raise CredentialResolutionError(
                    f"Could not resolve server-side credential for identifier '{self.credential_reference.credential_id}'"
                )

            header_name = self.credential_reference.auth_header_name or "Authorization"
            scheme = self.credential_reference.auth_scheme
            if scheme:
                headers[header_name] = f"{scheme} {secret_val}"
            else:
                headers[header_name] = secret_val

        # 4. Prepare Payload / Query params
        params: Optional[Dict[str, Any]] = None
        json_body: Optional[Dict[str, Any]] = None

        if self.method in ("GET", "DELETE"):
            params = remaining_args if remaining_args else None
        else:
            headers["Content-Type"] = "application/json"
            json_body = remaining_args

        # 5. Execute with Bounded Retries, Granular Timeouts & Redirect Validation
        can_retry = (not self.is_side_effecting) or bool(context.idempotency_key)
        total_attempts = (1 + self.max_retries) if can_retry else 1

        last_error: Optional[Exception] = None
        response_data: Optional[Dict[str, Any]] = None

        timeout_config = httpx.Timeout(
            timeout=self.timeout_seconds,
            connect=min(5.0, self.timeout_seconds),
            read=self.timeout_seconds,
            write=min(5.0, self.timeout_seconds),
            pool=min(5.0, self.timeout_seconds),
        )

        max_response_bytes = getattr(settings, "MAX_HTTP_TOOL_RESPONSE_BYTES", 2 * 1024 * 1024)
        max_redirect_hops = getattr(settings, "MAX_HTTP_TOOL_REDIRECTS", 3)

        for attempt in range(1, total_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout_config, follow_redirects=False) as client:
                    current_url = full_url
                    current_method = self.method
                    current_headers = dict(headers)
                    current_params = params
                    current_json = json_body
                    redirect_hops = 0

                    while True:
                        resp = await client.request(
                            method=current_method,
                            url=current_url,
                            params=current_params,
                            json=current_json,
                            headers=current_headers,
                        )

                        # Handle redirects with manual SSRF validation
                        if resp.status_code in (301, 302, 303, 307, 308):
                            location = resp.headers.get("Location")
                            if not location:
                                raise ToolExecutionError(
                                    f"HTTP redirect response ({resp.status_code}) missing Location header.",
                                    details={"status_code": resp.status_code, "tool_name": self.name},
                                )

                            redirect_hops += 1
                            if redirect_hops > max_redirect_hops:
                                raise ToolExecutionError(
                                    f"HTTP request exceeded maximum allowed redirect hops ({max_redirect_hops}).",
                                    details={"tool_name": self.name, "max_redirects": max_redirect_hops},
                                )

                            target_url = urljoin(current_url, location)
                            # Validate every redirect target before following
                            validate_destination_url(target_url, allow_http=allow_http)

                            # Strip credentials and idempotency keys across cross-origin redirects
                            from urllib.parse import urlparse
                            curr_p = urlparse(current_url)
                            targ_p = urlparse(target_url)
                            if (curr_p.scheme, curr_p.netloc) != (targ_p.scheme, targ_p.netloc):
                                current_headers.pop("Authorization", None)
                                if self.credential_reference and self.credential_reference.auth_header_name:
                                    current_headers.pop(self.credential_reference.auth_header_name, None)
                                current_headers.pop("Idempotency-Key", None)

                            if resp.status_code == 303:
                                current_method = "GET"
                                current_params = None
                                current_json = None

                            current_url = target_url
                            continue

                        # Check retryable 5xx status codes
                        if resp.status_code in RETRYABLE_STATUS_CODES and attempt < total_attempts:
                            logger.warning(
                                "Transient HTTP %s from '%s' on attempt %s/%s. Retrying...",
                                resp.status_code,
                                current_url,
                                attempt,
                                total_attempts,
                            )
                            await asyncio.sleep(0.2 * (2 ** (attempt - 1)))
                            break  # Break redirect loop to retry outer attempt

                        # Enforce Content-Length header limit if provided
                        cl_header = resp.headers.get("Content-Length")
                        if cl_header:
                            try:
                                cl_bytes = int(cl_header)
                                if cl_bytes > max_response_bytes:
                                    raise ToolExecutionError(
                                        f"HTTP response Content-Length ({cl_bytes} bytes) exceeds maximum limit of {max_response_bytes} bytes.",
                                        details={"tool_name": self.name, "content_length": cl_bytes, "max_bytes": max_response_bytes},
                                    )
                            except ValueError:
                                pass

                        # Enforce response content size limit
                        content_bytes = resp.content if hasattr(resp, "content") else b""
                        if len(content_bytes) > max_response_bytes:
                            raise ToolExecutionError(
                                f"HTTP response size ({len(content_bytes)} bytes) exceeded maximum allowed limit of {max_response_bytes} bytes.",
                                details={"tool_name": self.name, "max_bytes": max_response_bytes},
                            )

                        if resp.status_code >= 400:
                            # Non-retryable HTTP error
                            text_snippet = scrub_secrets(resp.text[:500] if hasattr(resp, "text") else "")
                            raise ToolExecutionError(
                                f"External tool HTTP request failed with status {resp.status_code}: {text_snippet}",
                                details={"status_code": resp.status_code, "tool_name": self.name},
                            )

                        # Parse JSON response
                        try:
                            response_data = resp.json() if (hasattr(resp, "text") and resp.text) else {}
                        except Exception:
                            response_data = {"raw_content": resp.text[:1000] if hasattr(resp, "text") else ""}

                        break  # Successfully handled response, break redirect loop

                if response_data is not None:
                    break  # Success, exit retry loop

            except (SSRFBlockedError, ToolExecutionError, ToolValidationError, CredentialResolutionError):
                # Security violations and hard tool errors must NEVER retry
                raise

            except httpx.TimeoutException as te:
                last_error = te
                if attempt < total_attempts:
                    logger.warning(
                        "Timeout calling '%s' on attempt %s/%s. Retrying...",
                        full_url,
                        attempt,
                        total_attempts,
                    )
                    await asyncio.sleep(0.2 * (2 ** (attempt - 1)))
                    continue
                else:
                    raise ToolTimeoutError(
                        f"Tool '{self.name}' timed out after {self.timeout_seconds}s.",
                        details={"tool_name": self.name, "timeout_seconds": self.timeout_seconds},
                    )

            except httpx.RequestError as re:
                last_error = re
                if attempt < total_attempts:
                    logger.warning(
                        "Network error calling '%s' on attempt %s/%s: %s. Retrying...",
                        full_url,
                        attempt,
                        total_attempts,
                        str(re),
                    )
                    await asyncio.sleep(0.2 * (2 ** (attempt - 1)))
                    continue
                else:
                    raise ToolExecutionError(
                        f"External tool network failure: {str(re)}",
                        details={"tool_name": self.name},
                    )

        if response_data is None:
            raise ToolExecutionError(
                f"Tool '{self.name}' execution failed: {str(last_error)}",
                details={"tool_name": self.name},
            )

        # 6. Validate Output Schema
        try:
            return self.output_schema.model_validate(response_data)
        except ValidationError as ve:
            raise ToolValidationError(
                f"External tool response failed output schema validation: {str(ve)}",
                details={"tool_name": self.name},
            )

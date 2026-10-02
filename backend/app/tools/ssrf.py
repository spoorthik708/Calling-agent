"""SSRF (Server-Side Request Forgery) Protection Module.

Enforces strict network security boundaries for external HTTP API tool executions:
1. Scheme validation (HTTPS required by default in production; unsupported schemes blocked).
2. Hostname sanity checks (loopback, internal TLDs, and cloud metadata hostnames blocked).
3. Blocking of userinfo / credentials in URLs to prevent hostname confusion (e.g., http://user@internal/).
4. Blocking of path traversal and null bytes in target paths.
5. Synchronous DNS pre-resolution via socket.getaddrinfo.
6. Comprehensive IP address analysis via Python ipaddress module:
   - Loopback (127.0.0.0/8, ::1)
   - Private RFC1918 (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16) and IPv6 Unique Local (fc00::/7)
   - Link-local (169.254.0.0/16, fe80::/10)
   - Cloud metadata endpoints (169.254.169.254, fd00:ec2::254)
   - Multicast, unspecified, and reserved ranges

DNS REBINDING / TOCTOU LIMITATION NOTICE:
In standard Python HTTP transport stacks (including httpx, requests, urllib3), the operating
system performs a secondary DNS resolution at the exact moment the socket connects.
Pre-flight DNS validation checks all addresses returned by getaddrinfo at T0.
However, in theory, a malicious domain with a sub-second TTL could return a benign IP at T0
and rebind to a private/internal IP at T1 (socket connect time).
True socket-level IP pinning requires custom C-level network hook or an egress filtering proxy
(e.g., Stripe Smokescreen or Envoy). We provide the strongest safe application-layer protection
available without replacing the standard Python async networking stack:
- Pre-flight DNS resolution of all address family records (IPv4 & IPv6).
- Strict validation of all redirect locations on every hop before making the subsequent request.
- Automatic header stripping across redirect origins.
- Strict response-size and timeout bounding.
"""

import ipaddress
import socket
from typing import List, Optional, Set, Tuple
from urllib.parse import urlparse

from app.core.exceptions import SSRFBlockedError
from app.core.logging import get_logger

logger = get_logger("yavura.tools.ssrf")

# Prohibited internal hostnames and domain suffixes
BLOCKED_HOSTNAMES: Set[str] = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "instance-data",
    "metadata.packet.net",
}

BLOCKED_SUFFIXES: Tuple[str, ...] = (
    ".local",
    ".internal",
    ".localhost",
    ".corp",
    ".lan",
    ".home",
    ".intranet",
    ".onion",
)

CLOUD_METADATA_IPS: Set[str] = {
    "169.254.169.254",
    "fd00:ec2::254",
}


def validate_destination_url(
    url: str,
    allow_http: bool = False,
) -> Tuple[str, List[str]]:
    """
    Validates that a URL does not point to internal network services, loopback,
    private IP ranges, or cloud metadata endpoints.

    Args:
        url: The absolute target URL.
        allow_http: Whether HTTP is allowed (strictly for testing; default False).

    Returns:
        Tuple of (normalized_url, list of resolved public IP strings).

    Raises:
        SSRFBlockedError: If the target violates any SSRF security boundary.
    """
    if not url or not isinstance(url, str):
        raise SSRFBlockedError(
            message="Target URL cannot be empty.",
            details={"url": url},
        )

    try:
        parsed = urlparse(url.strip())
    except Exception as exc:
        raise SSRFBlockedError(
            message=f"Invalid URL structure: {str(exc)}",
            details={"url": url},
        )

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("https", "http"):
        raise SSRFBlockedError(
            message=f"URL scheme '{scheme}' is forbidden. Only HTTPS is allowed.",
            details={"url": url, "scheme": scheme},
        )

    if scheme == "http" and not allow_http:
        raise SSRFBlockedError(
            message="Unencrypted HTTP is prohibited for external tool calls. Use HTTPS.",
            details={"url": url, "scheme": scheme},
        )

    hostname = (parsed.hostname or "").lower().strip()
    if not hostname:
        raise SSRFBlockedError(
            message="URL must contain a valid hostname.",
            details={"url": url},
        )

    # Block userinfo / embedded credentials (prevents hostname confusion via @)
    if parsed.username or parsed.password or "@" in (parsed.netloc or ""):
        raise SSRFBlockedError(
            message="Embedded credentials or userinfo in target URL is strictly prohibited.",
            details={"url": url},
        )

    # Block path traversal and null bytes in path
    from urllib.parse import unquote
    raw_path = parsed.path or ""
    decoded_path = unquote(raw_path)
    if "\x00" in raw_path or "\x00" in decoded_path:
        raise SSRFBlockedError("Null bytes in target URL path are prohibited.", details={"url": url})
    if "/../" in raw_path or raw_path.endswith("/..") or "/../" in decoded_path or decoded_path.endswith("/..") or "\\..\\" in decoded_path:
        raise SSRFBlockedError("Path traversal sequences in target URL are prohibited.", details={"url": url})

    # 1. Prohibited hostname checks
    if hostname in BLOCKED_HOSTNAMES:
        raise SSRFBlockedError(
            message=f"Access to prohibited hostname '{hostname}' is blocked.",
            details={"url": url, "hostname": hostname},
        )

    for suffix in BLOCKED_SUFFIXES:
        if hostname.endswith(suffix):
            raise SSRFBlockedError(
                message=f"Access to internal domain suffix '{suffix}' is blocked.",
                details={"url": url, "hostname": hostname},
            )

    # 2. Port validation
    port = parsed.port
    if port is None:
        port = 443 if scheme == "https" else 80
    elif port < 1 or port > 65535:
        raise SSRFBlockedError(
            message=f"Invalid network port '{port}'.",
            details={"url": url, "port": port},
        )

    # 3. DNS Resolution and IP checks
    resolved_ips: List[str] = []
    try:
        addr_info = socket.getaddrinfo(
            hostname,
            port,
            proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror as gai:
        raise SSRFBlockedError(
            message=f"Could not resolve destination hostname '{hostname}': {str(gai)}",
            details={"url": url, "hostname": hostname},
        )

    for entry in addr_info:
        sockaddr = entry[4]
        ip_str = sockaddr[0]

        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            raise SSRFBlockedError(
                message=f"Resolved invalid IP address '{ip_str}' for host '{hostname}'.",
                details={"hostname": hostname, "ip": ip_str},
            )

        # Explicit check for cloud metadata
        if ip_str in CLOUD_METADATA_IPS:
            raise SSRFBlockedError(
                message="Access to cloud metadata service IP address is strictly prohibited.",
                details={"hostname": hostname, "ip": ip_str},
            )

        # RFC1918 / Loopback / Link-Local / Reserved / Multicast checks
        if ip_obj.is_loopback:
            raise SSRFBlockedError(
                message=f"Access to loopback IP address '{ip_str}' is prohibited.",
                details={"hostname": hostname, "ip": ip_str},
            )
        if ip_obj.is_private:
            raise SSRFBlockedError(
                message=f"Access to private/internal IP address '{ip_str}' is prohibited.",
                details={"hostname": hostname, "ip": ip_str},
            )
        if ip_obj.is_link_local:
            raise SSRFBlockedError(
                message=f"Access to link-local IP address '{ip_str}' is prohibited.",
                details={"hostname": hostname, "ip": ip_str},
            )
        if ip_obj.is_reserved:
            raise SSRFBlockedError(
                message=f"Access to reserved IP address '{ip_str}' is prohibited.",
                details={"hostname": hostname, "ip": ip_str},
            )
        if ip_obj.is_multicast:
            raise SSRFBlockedError(
                message=f"Access to multicast IP address '{ip_str}' is prohibited.",
                details={"hostname": hostname, "ip": ip_str},
            )
        if ip_obj.is_unspecified:
            raise SSRFBlockedError(
                message=f"Access to unspecified IP address '{ip_str}' is prohibited.",
                details={"hostname": hostname, "ip": ip_str},
            )

        resolved_ips.append(ip_str)

    if not resolved_ips:
        raise SSRFBlockedError(
            message=f"No routable public IP addresses found for hostname '{hostname}'.",
            details={"hostname": hostname},
        )

    logger.debug("SSRF check passed for '%s' -> %s", url, resolved_ips)
    return url, resolved_ips

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib import request
from urllib.parse import urlparse

_LOCAL_HTTP_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_EXTERNAL_SOURCE_ID_PREFIXES = ("arxiv:", "doi:")


class _NoRedirectHandler(request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_NO_REDIRECT_OPENER = request.build_opener(_NoRedirectHandler)


def secure_default_service_url(host: str, port: int, *, path: str = "") -> str:
    """Return a placeholder service URL defaulting to HTTPS except on loopback."""
    normalized_host = host.strip().lower()
    scheme = "http" if normalized_host in _LOCAL_HTTP_HOSTS else "https"
    normalized_path = path if not path or path.startswith("/") else f"/{path}"
    return f"{scheme}://{host.strip()}:{port}{normalized_path}"


def looks_like_external_source_reference(value: str) -> bool:
    """Return True when a persisted source id or URL points outside local-only artifacts."""
    text = str(value or "").strip().lower()
    if not text:
        return False
    if text.startswith(_EXTERNAL_SOURCE_ID_PREFIXES):
        return True
    try:
        parsed = urlparse(text)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _ip_is_private_target(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )


def _parse_ip_literal(
    host: str,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    # urllib/socket may accept integer IPv4 forms such as 2130706433 for 127.0.0.1.
    if host.isdecimal():
        try:
            return ipaddress.ip_address(int(host))
        except ValueError:
            return None
    return None


def _resolved_ips(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    literal = _parse_ip_literal(host)
    if literal is not None:
        return [literal]
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for family, _type, _proto, _canonname, sockaddr in socket.getaddrinfo(host, None):
        if family not in {socket.AF_INET, socket.AF_INET6}:
            continue
        addresses.append(ipaddress.ip_address(sockaddr[0]))
    return addresses


def validate_http_url(
    url: str,
    *,
    field_name: str = "url",
    allow_private: bool = False,
    resolve_host: bool = False,
) -> str:
    """Return a stripped URL only when it targets HTTP(S) safely.

    Operator-provided URLs cross high-agency boundaries (callbacks, alerts,
    worker dispatch, provider probes). Validate the authority we are about to
    connect to, and reject local/internal targets unless the caller explicitly
    opts into a local-dev/private-network flow.
    """
    value = str(url or "").strip()
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError(f"{field_name} must not contain control characters")
    if "\\" in value:
        raise ValueError(f"{field_name} must not contain backslashes")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"{field_name} must use http or https")
    if not parsed.netloc or not parsed.hostname:
        raise ValueError(f"{field_name} must include a host")
    if parsed.username or parsed.password:
        raise ValueError(f"{field_name} must not include userinfo")
    literal = _parse_ip_literal(parsed.hostname)
    try:
        ips = (
            _resolved_ips(parsed.hostname)
            if resolve_host
            else ([literal] if literal else [])
        )
    except (OSError, ValueError) as exc:
        raise ValueError(f"{field_name} host could not be resolved") from exc
    if resolve_host and not ips:
        raise ValueError(f"{field_name} host could not be resolved")
    if not allow_private:
        blocked = [ip for ip in ips if _ip_is_private_target(ip)]
        if blocked:
            raise ValueError(f"{field_name} must not resolve to a private address")
    return value


def urlopen_validated(
    req_or_url: request.Request | str,
    *,
    timeout: float,
    field_name: str = "url",
    allow_private: bool = False,
) -> Any:
    """Open a validated HTTP(S) URL without following redirects."""
    url = req_or_url.full_url if isinstance(req_or_url, request.Request) else req_or_url
    validate_http_url(
        url, field_name=field_name, allow_private=allow_private, resolve_host=True
    )
    return _NO_REDIRECT_OPENER.open(req_or_url, timeout=timeout)

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager

import ipaddress
import socket
from collections.abc import Generator
from typing import Any, cast
from urllib import request
from urllib.parse import urlparse


_logger = logging.getLogger(__name__)

_LOCAL_HTTP_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_EXTERNAL_SOURCE_ID_PREFIXES = ("arxiv:", "doi:")


class _NoRedirectHandler(request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_NO_REDIRECT_OPENER = request.build_opener(_NoRedirectHandler)
_PINNED_DNS_LOCK = threading.RLock()


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
    except ValueError as exc:
        _logger.debug(
            "host is not a direct IP literal; trying numeric IPv4 fallback",
            exc_info=exc,
        )
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


def _default_port_for_scheme(scheme: str) -> int:
    if scheme == "http":
        return 80
    if scheme == "https":
        return 443
    raise ValueError("unsupported URL scheme")


def _addrinfo_ips(
    addrinfo: list[tuple[int, int, int, str, tuple[Any, ...]]],
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for family, _type, _proto, _canonname, sockaddr in addrinfo:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            continue
        ips.append(ipaddress.ip_address(sockaddr[0]))
    return ips


def _resolved_addrinfo(
    host: str, port: int
) -> list[tuple[int, int, int, str, tuple[Any, ...]]]:
    literal = _parse_ip_literal(host)
    if literal is not None:
        family = socket.AF_INET6 if literal.version == 6 else socket.AF_INET
        sockaddr: tuple[Any, ...]
        if literal.version == 6:
            sockaddr = (str(literal), port, 0, 0)
        else:
            sockaddr = (str(literal), port)
        return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)]
    return cast(
        list[tuple[int, int, int, str, tuple[Any, ...]]],
        socket.getaddrinfo(host, port, type=socket.SOCK_STREAM),
    )


@contextmanager
def _pin_getaddrinfo(
    *,
    host: str,
    port: int,
    addrinfo: list[tuple[int, int, int, str, tuple[Any, ...]]],
) -> Generator[None, None, None]:
    original_getaddrinfo = socket.getaddrinfo
    normalized_host = host.rstrip(".").lower()

    def pinned_getaddrinfo(
        query_host: str,
        query_port: int | str | None,
        family: int = 0,
        type: int = 0,  # noqa: A002 - match socket.getaddrinfo signature
        proto: int = 0,
        flags: int = 0,
    ) -> list[tuple[int, int, int, str, tuple[Any, ...]]]:
        del flags
        query_host_normalized = str(query_host or "").rstrip(".").lower()
        query_port_int = int(query_port) if query_port is not None else port
        if query_host_normalized != normalized_host or query_port_int != port:
            return cast(
                list[tuple[int, int, int, str, tuple[Any, ...]]],
                original_getaddrinfo(query_host, query_port, family, type, proto),
            )
        pinned: list[tuple[int, int, int, str, tuple[Any, ...]]] = []
        for item in addrinfo:
            item_family, item_type, item_proto, _canonname, _sockaddr = item
            if family not in (0, item_family):
                continue
            if type not in (0, item_type):
                continue
            if proto not in (0, item_proto):
                continue
            pinned.append(item)
        if not pinned:
            raise socket.gaierror(
                socket.EAI_NONAME, "no pinned address matched request"
            )
        return pinned

    with _PINNED_DNS_LOCK:
        socket.getaddrinfo = pinned_getaddrinfo
        try:
            yield
        finally:
            socket.getaddrinfo = original_getaddrinfo


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
    validated_url = validate_http_url(
        url, field_name=field_name, allow_private=allow_private, resolve_host=False
    )
    parsed = urlparse(validated_url)
    host = parsed.hostname
    if host is None:
        raise ValueError(f"{field_name} must include a host")
    port = parsed.port or _default_port_for_scheme(parsed.scheme)
    try:
        addrinfo = _resolved_addrinfo(host, port)
    except (OSError, ValueError) as exc:
        raise ValueError(f"{field_name} host could not be resolved") from exc
    ips = _addrinfo_ips(addrinfo)
    if not ips:
        raise ValueError(f"{field_name} host could not be resolved")
    if not allow_private and any(_ip_is_private_target(ip) for ip in ips):
        raise ValueError(f"{field_name} must not resolve to a private address")
    with _pin_getaddrinfo(host=host, port=port, addrinfo=addrinfo):
        return _NO_REDIRECT_OPENER.open(req_or_url, timeout=timeout)

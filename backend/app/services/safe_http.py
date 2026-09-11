"""Bounded, SSRF-resistant HTTP fetching for untrusted article URLs.

The standard ``httpx`` redirect flow is intentionally not used here.  Each
redirect target is validated before the next request, and the production
transport resolves and pins a validated public IP before opening a socket.
That prevents a DNS rebinding between validation and connection.
"""
from __future__ import annotations

import asyncio
import email.utils
import ipaddress
import socket
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Iterable, Mapping
from urllib.parse import urldefrag, urljoin, urlparse

import httpcore
import httpx


Resolver = Callable[[str, int], Awaitable[Iterable[str]]]

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; DailyNewsBot/1.0)"


class SafeFetchError(Exception):
    """A fetch failure with a stable machine-readable code."""

    def __init__(
        self,
        code: str,
        message: str = "",
        *,
        url: str = "",
        status_code: int | None = None,
        reason: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.url = url
        self.status_code = status_code
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class SafeFetchPolicy:
    """Policy controls for one class of untrusted fetches.

    ``allowed_hosts`` is an optional publisher/source allowlist.  Subdomains
    are accepted by default, but lookalike suffixes are not.  It is separate
    from the mandatory public-address checks.
    """

    timeout_seconds: float = 15.0
    max_redirects: int = 3
    max_wire_bytes: int = 2_000_000
    max_decoded_bytes: int = 2_000_000
    allowed_content_types: tuple[str, ...] | None = (
        "text/html",
        "application/xhtml+xml",
    )
    allowed_hosts: frozenset[str] | None = None
    allow_subdomains: bool = True
    allow_https_downgrade: bool = False
    allowed_ports: frozenset[int] | None = frozenset({80, 443})
    user_agent: str = _DEFAULT_USER_AGENT

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_redirects < 0:
            raise ValueError("max_redirects cannot be negative")
        if self.max_wire_bytes <= 0 or self.max_decoded_bytes <= 0:
            raise ValueError("response size limits must be positive")


@dataclass(frozen=True)
class SafeFetchResult:
    url: str
    status_code: int
    headers: Mapping[str, str]
    content_type: str
    body: bytes
    wire_bytes: int
    decoded_bytes: int
    redirect_count: int

    @property
    def text(self) -> str:
        content_type = self.headers.get("content-type", "")
        encoding = "utf-8"
        for part in content_type.split(";")[1:]:
            key, separator, value = part.strip().partition("=")
            if separator and key.lower() == "charset" and value.strip():
                encoding = value.strip().strip('"\'')
                break
        try:
            return self.body.decode(encoding, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


def normalize_host(host: str) -> str:
    """Normalize a host for exact/subdomain policy comparisons."""
    normalized = host.strip().rstrip(".").lower()
    if not normalized:
        return ""
    try:
        return normalized.encode("idna").decode("ascii")
    except UnicodeError:
        return ""


def hosts_match(host: str, allowed_host: str, *, allow_subdomains: bool = True) -> bool:
    host = normalize_host(host)
    allowed_host = normalize_host(allowed_host)
    if not host or not allowed_host:
        return False
    # Publishers routinely canonicalize ``www.example.com`` to ``example.com``
    # (and back). Treat only that conventional alias as the same policy host;
    # all other sibling or lookalike domains still require explicit approval.
    policy_host = host[4:] if host.startswith("www.") else host
    policy_allowed = (
        allowed_host[4:] if allowed_host.startswith("www.") else allowed_host
    )
    return policy_host == policy_allowed or (
        allow_subdomains and policy_host.endswith(f".{policy_allowed}")
    )


def is_public_ip(address: str) -> bool:
    """Return true only for globally routable unicast IP addresses."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


async def resolve_addresses(host: str, port: int) -> tuple[str, ...]:
    """Resolve a hostname without blocking the event loop."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except (socket.gaierror, OSError) as exc:
        raise SafeFetchError("dns_failure", str(exc), url=host) from exc

    addresses = tuple(dict.fromkeys(info[4][0] for info in infos if info[4]))
    if not addresses:
        raise SafeFetchError("dns_failure", "DNS returned no addresses", url=host)
    return addresses


async def _validated_addresses(
    host: str,
    port: int,
    resolver: Resolver,
) -> tuple[str, ...]:
    try:
        addresses = tuple(dict.fromkeys(await resolver(host, port)))
    except SafeFetchError:
        raise
    except Exception as exc:
        raise SafeFetchError("dns_failure", str(exc), url=host) from exc

    if not addresses:
        raise SafeFetchError("dns_failure", "DNS returned no addresses", url=host)
    unsafe = [address for address in addresses if not is_public_ip(address)]
    if unsafe:
        raise SafeFetchError(
            "unsafe_address",
            "Host resolves to a non-public address",
            url=host,
        )
    return addresses


async def _validate_url(
    url: str,
    policy: SafeFetchPolicy,
    resolver: Resolver,
) -> tuple[str, str, int]:
    if not isinstance(url, str) or not url.strip() or len(url) > 4096:
        raise SafeFetchError("invalid_url", "URL is empty or too long", url=str(url))

    if any(ord(character) < 32 or ord(character) == 127 for character in url):
        raise SafeFetchError("invalid_url", "URL contains control characters", url=url)

    clean_url, _fragment = urldefrag(url.strip())
    try:
        parsed = urlparse(clean_url)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise SafeFetchError("invalid_url", str(exc), url=clean_url) from exc

    if parsed.scheme.lower() not in {"http", "https"}:
        raise SafeFetchError("unsafe_scheme", "Only HTTP(S) URLs are allowed", url=clean_url)
    if parsed.username is not None or parsed.password is not None:
        raise SafeFetchError("credentials_not_allowed", url=clean_url)

    host = normalize_host(parsed.hostname or "")
    if not host:
        raise SafeFetchError("missing_host", url=clean_url)

    effective_port = port or (443 if parsed.scheme.lower() == "https" else 80)
    if policy.allowed_ports is not None and effective_port not in policy.allowed_ports:
        raise SafeFetchError("port_not_allowed", url=clean_url)

    if policy.allowed_hosts is not None and not any(
        hosts_match(host, allowed, allow_subdomains=policy.allow_subdomains)
        for allowed in policy.allowed_hosts
    ):
        raise SafeFetchError("host_not_allowed", url=clean_url)

    try:
        literal_ip = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        await _validated_addresses(host, effective_port, resolver)
    else:
        if not is_public_ip(str(literal_ip)):
            raise SafeFetchError("unsafe_address", url=clean_url)

    return clean_url, host, effective_port


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Resolve, validate, and connect to the same IP to close DNS-rebind TOCTOU."""

    def __init__(self, resolver: Resolver) -> None:
        self._resolver = resolver
        # AnyIOBackend is part of httpcore's public API. HTTPX 0.27.2 does not
        # expose a supported hook for replacing DNS resolution, so the small
        # pool integration below is version-pinned and covered by a smoke test.
        self._backend = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ):
        normalized = normalize_host(host.decode("ascii") if isinstance(host, bytes) else host)
        try:
            literal = ipaddress.ip_address(normalized.split("%", 1)[0])
            addresses = (str(literal),)
        except ValueError:
            addresses = await _validated_addresses(normalized, port, self._resolver)

        last_error: Exception | None = None
        for address in addresses:
            try:
                return await self._backend.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except Exception as exc:  # try every validated A/AAAA result
                last_error = exc
        assert last_error is not None
        raise last_error

    async def connect_unix_socket(self, *args, **kwargs):
        raise SafeFetchError("unix_socket_not_allowed")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class _PinnedHTTPTransport(httpx.AsyncHTTPTransport):
    """HTTPX transport whose connection pool uses the pinned DNS backend."""

    def __init__(self, resolver: Resolver) -> None:
        # The project pins HTTPX; replacing its pool is intentionally localized
        # here so the rest of the code never relies on transport internals.
        super().__init__(verify=True, trust_env=False, retries=0)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(),
            max_connections=20,
            max_keepalive_connections=10,
            keepalive_expiry=5.0,
            http1=True,
            http2=False,
            retries=0,
            network_backend=_PinnedNetworkBackend(resolver),
        )


def _content_type_allowed(content_type: str, allowed: tuple[str, ...] | None) -> bool:
    if allowed is None:
        return True
    media_type = content_type.split(";", 1)[0].strip().lower()
    return any(media_type == candidate.lower() for candidate in allowed)


def _parse_retry_after(value: str | None, *, now: datetime | None = None) -> int | None:
    """Parse Retry-After without allowing an origin to schedule unbounded work."""
    if not value:
        return None
    raw = value.strip()
    if raw.isdecimal():
        return min(int(raw), 86_400)
    try:
        retry_at = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    return min(max(0, int((retry_at - current).total_seconds())), 86_400)


async def safe_fetch(
    url: str,
    *,
    policy: SafeFetchPolicy | None = None,
    resolver: Resolver | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> SafeFetchResult:
    """Fetch an untrusted URL under strict redirect, network, type, and size limits.

    ``resolver`` and ``transport`` are injectable for deterministic tests.  A
    caller-provided transport is never used by production call sites; the
    default transport pins validated DNS results before connecting.
    """
    policy = policy or SafeFetchPolicy()
    resolver = resolver or resolve_addresses
    current_url = url
    seen_urls: set[str] = set()
    redirect_count = 0
    selected_transport = transport or _PinnedHTTPTransport(resolver)
    timeout = httpx.Timeout(
        policy.timeout_seconds,
        connect=min(policy.timeout_seconds, 5.0),
    )

    try:
        # HTTPX timeouts are per network operation. The outer deadline also
        # bounds slow DNS and slow-loris responses that keep yielding chunks.
        async with asyncio.timeout(policy.timeout_seconds):
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
                transport=selected_transport,
            ) as client:
                while True:
                    try:
                        current_url, _host, _port = await _validate_url(
                            current_url,
                            policy,
                            resolver,
                        )
                    except SafeFetchError as exc:
                        if redirect_count:
                            raise SafeFetchError(
                                "unsafe_redirect",
                                "Redirect target failed safety validation",
                                url=current_url,
                                reason=exc.code,
                            ) from exc
                        raise

                    if current_url in seen_urls:
                        raise SafeFetchError("redirect_loop", url=current_url)
                    seen_urls.add(current_url)

                    try:
                        async with client.stream(
                            "GET",
                            current_url,
                            headers={
                                "User-Agent": policy.user_agent,
                                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
                                "Accept-Encoding": "gzip, deflate",
                            },
                        ) as response:
                            if response.status_code in _REDIRECT_STATUSES:
                                location = response.headers.get("location", "").strip()
                                if not location:
                                    raise SafeFetchError(
                                        "redirect_missing_location",
                                        url=current_url,
                                        status_code=response.status_code,
                                    )
                                if redirect_count >= policy.max_redirects:
                                    raise SafeFetchError("redirect_limit", url=current_url)
                                next_url = urljoin(current_url, location)
                                if (
                                    not policy.allow_https_downgrade
                                    and urlparse(current_url).scheme.lower() == "https"
                                    and urlparse(next_url).scheme.lower() == "http"
                                ):
                                    raise SafeFetchError(
                                        "unsafe_redirect",
                                        "HTTPS redirect cannot downgrade to HTTP",
                                        url=next_url,
                                        reason="https_downgrade",
                                    )
                                current_url = next_url
                                redirect_count += 1
                                continue

                            if response.status_code < 200 or response.status_code >= 300:
                                raise SafeFetchError(
                                    "http_status",
                                    f"Unexpected HTTP status {response.status_code}",
                                    url=current_url,
                                    status_code=response.status_code,
                                    retry_after_seconds=_parse_retry_after(
                                        response.headers.get("retry-after")
                                    ),
                                )

                            content_type = response.headers.get("content-type", "")
                            if not _content_type_allowed(content_type, policy.allowed_content_types):
                                raise SafeFetchError(
                                    "unsupported_content_type",
                                    content_type or "missing content type",
                                    url=current_url,
                                )

                            content_encoding = response.headers.get(
                                "content-encoding", "identity"
                            ).lower()
                            encodings = {
                                item.strip()
                                for item in content_encoding.split(",")
                                if item.strip()
                            }
                            if not encodings.issubset({"identity", "gzip", "deflate"}):
                                raise SafeFetchError(
                                    "unsupported_content_encoding",
                                    content_encoding,
                                    url=current_url,
                                )

                            raw_length = response.headers.get("content-length", "")
                            try:
                                declared_length = int(raw_length)
                            except (TypeError, ValueError):
                                declared_length = 0
                            if declared_length > policy.max_wire_bytes:
                                raise SafeFetchError("response_too_large", url=current_url)

                            chunks: list[bytes] = []
                            decoded_bytes = 0
                            wire_bytes = 0
                            async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                                wire_bytes = max(wire_bytes, response.num_bytes_downloaded)
                                decoded_bytes += len(chunk)
                                if (
                                    wire_bytes > policy.max_wire_bytes
                                    or decoded_bytes > policy.max_decoded_bytes
                                ):
                                    raise SafeFetchError("response_too_large", url=current_url)
                                chunks.append(chunk)

                            return SafeFetchResult(
                                url=str(response.url),
                                status_code=response.status_code,
                                headers=dict(response.headers),
                                content_type=content_type.split(";", 1)[0].strip().lower(),
                                body=b"".join(chunks),
                                wire_bytes=wire_bytes,
                                decoded_bytes=decoded_bytes,
                                redirect_count=redirect_count,
                            )
                    except SafeFetchError:
                        raise
                    except (httpx.TimeoutException, httpcore.TimeoutException) as exc:
                        raise SafeFetchError("timeout", str(exc), url=current_url) from exc
                    except (httpx.HTTPError, httpcore.NetworkError) as exc:
                        raise SafeFetchError("network_error", str(exc), url=current_url) from exc
    except TimeoutError as exc:
        raise SafeFetchError(
            "timeout",
            "Total fetch deadline exceeded",
            url=current_url,
        ) from exc

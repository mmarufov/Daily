"""Adversarial contract tests for untrusted publisher fetching."""
from __future__ import annotations

import asyncio
import importlib
import importlib.metadata
import sys
import types
import unittest


def _real_module(name: str):
    """Replace the suite's lightweight import stub for dependency-level tests."""
    existing = sys.modules.get(name)
    if isinstance(existing, types.ModuleType) and getattr(existing, "__spec__", None):
        return existing
    sys.modules.pop(name, None)
    return importlib.import_module(name)


httpx = _real_module("httpx")
sys.modules.pop("app.services.safe_http", None)

from app.services.safe_http import (  # noqa: E402
    SafeFetchError,
    SafeFetchPolicy,
    _PinnedHTTPTransport,
    _PinnedNetworkBackend,
    hosts_match,
    safe_fetch,
)


PUBLIC_IP = "93.184.216.34"


async def _public_resolver(_host: str, _port: int) -> tuple[str, ...]:
    return (PUBLIC_IP,)


class SafeFetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_follows_only_manually_validated_same_source_redirects(self):
        requested: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(str(request.url))
            if request.url.path == "/old":
                return httpx.Response(302, headers={"location": "/story"})
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                content=b"<html>story</html>",
            )

        result = await safe_fetch(
            "https://publisher.example/old",
            policy=SafeFetchPolicy(
                allowed_hosts=frozenset({"publisher.example"}),
            ),
            resolver=_public_resolver,
            transport=httpx.MockTransport(handler),
        )

        self.assertEqual(requested, [
            "https://publisher.example/old",
            "https://publisher.example/story",
        ])
        self.assertEqual(result.redirect_count, 1)
        self.assertEqual(result.url, "https://publisher.example/story")

    async def test_rejects_private_redirect_before_second_request(self):
        requested: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(str(request.url))
            return httpx.Response(
                302,
                headers={"location": "http://169.254.169.254/latest/meta-data"},
            )

        with self.assertRaises(SafeFetchError) as raised:
            await safe_fetch(
                "https://publisher.example/story",
                policy=SafeFetchPolicy(
                    allowed_hosts=frozenset({"publisher.example"}),
                ),
                resolver=_public_resolver,
                transport=httpx.MockTransport(handler),
            )

        self.assertEqual(raised.exception.code, "unsafe_redirect")
        self.assertIn(
            raised.exception.reason,
            {"host_not_allowed", "unsafe_address", "https_downgrade"},
        )
        self.assertEqual(requested, ["https://publisher.example/story"])

    async def test_rejects_public_cross_source_redirect_without_explicit_allowlist(self):
        requested: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(str(request.url))
            return httpx.Response(
                302,
                headers={"location": "https://other.example/story"},
            )

        with self.assertRaises(SafeFetchError) as raised:
            await safe_fetch(
                "https://publisher.example/story",
                policy=SafeFetchPolicy(
                    allowed_hosts=frozenset({"publisher.example"}),
                ),
                resolver=_public_resolver,
                transport=httpx.MockTransport(handler),
            )

        self.assertEqual(raised.exception.code, "unsafe_redirect")
        self.assertEqual(raised.exception.reason, "host_not_allowed")
        self.assertEqual(len(requested), 1)

    async def test_rejects_https_to_http_downgrade_before_second_request(self):
        requested: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(str(request.url))
            return httpx.Response(
                302,
                headers={"location": "http://publisher.example/story"},
            )

        with self.assertRaises(SafeFetchError) as raised:
            await safe_fetch(
                "https://publisher.example/story",
                policy=SafeFetchPolicy(
                    allowed_hosts=frozenset({"publisher.example"}),
                ),
                resolver=_public_resolver,
                transport=httpx.MockTransport(handler),
            )

        self.assertEqual(raised.exception.code, "unsafe_redirect")
        self.assertEqual(raised.exception.reason, "https_downgrade")
        self.assertEqual(requested, ["https://publisher.example/story"])

    async def test_rejects_mixed_public_and_private_dns_answers(self):
        async def mixed_resolver(_host: str, _port: int) -> tuple[str, ...]:
            return (PUBLIC_IP, "127.0.0.1")

        with self.assertRaises(SafeFetchError) as raised:
            await safe_fetch(
                "https://publisher.example/story",
                policy=SafeFetchPolicy(
                    allowed_hosts=frozenset({"publisher.example"}),
                ),
                resolver=mixed_resolver,
                transport=httpx.MockTransport(lambda _request: httpx.Response(200)),
            )

        self.assertEqual(raised.exception.code, "unsafe_address")

    async def test_rejects_wrong_or_missing_content_type(self):
        for content_type in ("application/pdf", ""):
            with self.subTest(content_type=content_type):
                headers = {"content-type": content_type} if content_type else {}
                with self.assertRaises(SafeFetchError) as raised:
                    await safe_fetch(
                        "https://publisher.example/story",
                        policy=SafeFetchPolicy(
                            allowed_hosts=frozenset({"publisher.example"}),
                        ),
                        resolver=_public_resolver,
                        transport=httpx.MockTransport(
                            lambda _request: httpx.Response(
                                200, headers=headers, content=b"not html"
                            )
                        ),
                    )
                self.assertEqual(raised.exception.code, "unsupported_content_type")

    async def test_enforces_declared_and_streamed_size_limits(self):
        cases = (
            httpx.Response(
                200,
                headers={"content-type": "text/html", "content-length": "500"},
                content=b"x",
            ),
            httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b"x" * 101,
            ),
        )
        for response in cases:
            with self.subTest(headers=dict(response.headers)):
                with self.assertRaises(SafeFetchError) as raised:
                    await safe_fetch(
                        "https://publisher.example/story",
                        policy=SafeFetchPolicy(
                            max_wire_bytes=100,
                            max_decoded_bytes=100,
                            allowed_hosts=frozenset({"publisher.example"}),
                        ),
                        resolver=_public_resolver,
                        transport=httpx.MockTransport(lambda _request, r=response: r),
                    )
                self.assertEqual(raised.exception.code, "response_too_large")

    async def test_propagates_bounded_retry_after(self):
        with self.assertRaises(SafeFetchError) as raised:
            await safe_fetch(
                "https://publisher.example/story",
                policy=SafeFetchPolicy(
                    allowed_hosts=frozenset({"publisher.example"}),
                ),
                resolver=_public_resolver,
                transport=httpx.MockTransport(
                    lambda _request: httpx.Response(
                        429,
                        headers={"retry-after": "999999"},
                    )
                ),
            )

        self.assertEqual(raised.exception.code, "http_status")
        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.retry_after_seconds, 86_400)

    async def test_total_deadline_also_bounds_dns(self):
        async def slow_resolver(_host: str, _port: int) -> tuple[str, ...]:
            await asyncio.sleep(1)
            return (PUBLIC_IP,)

        with self.assertRaises(SafeFetchError) as raised:
            await safe_fetch(
                "https://publisher.example/story",
                policy=SafeFetchPolicy(
                    timeout_seconds=0.01,
                    allowed_hosts=frozenset({"publisher.example"}),
                ),
                resolver=slow_resolver,
                transport=httpx.MockTransport(lambda _request: httpx.Response(200)),
            )

        self.assertEqual(raised.exception.code, "timeout")

    async def test_pinned_backend_connects_to_validated_ip_not_hostname(self):
        connected: list[str] = []

        class FakeBackend:
            async def connect_tcp(self, host, _port, **_kwargs):
                connected.append(host)
                return object()

            async def sleep(self, _seconds):
                return None

        backend = _PinnedNetworkBackend(_public_resolver)
        backend._backend = FakeBackend()
        await backend.connect_tcp("publisher.example", 443)

        self.assertEqual(connected, [PUBLIC_IP])

    async def test_pinned_backend_revalidates_dns_at_connection_time(self):
        async def rebound_resolver(_host: str, _port: int) -> tuple[str, ...]:
            return ("127.0.0.1",)

        backend = _PinnedNetworkBackend(rebound_resolver)
        with self.assertRaises(SafeFetchError) as raised:
            await backend.connect_tcp("publisher.example", 443)

        self.assertEqual(raised.exception.code, "unsafe_address")

    async def test_pinned_transport_matches_locked_dependency_versions(self):
        self.assertEqual(importlib.metadata.version("httpx"), "0.27.2")
        self.assertEqual(importlib.metadata.version("httpcore"), "1.0.9")
        transport = _PinnedHTTPTransport(_public_resolver)
        await transport.aclose()

    def test_host_policy_allows_www_alias_but_not_lookalikes(self):
        self.assertTrue(hosts_match("www.publisher.example", "publisher.example"))
        self.assertTrue(hosts_match("publisher.example", "www.publisher.example"))
        self.assertFalse(hosts_match("publisher.example.evil.test", "publisher.example"))
        self.assertFalse(hosts_match("notpublisher.example", "publisher.example"))


if __name__ == "__main__":
    unittest.main()

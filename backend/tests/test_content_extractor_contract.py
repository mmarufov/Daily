"""Reader-safety contract tests for publisher body extraction."""
from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch


def _real_module(name: str):
    existing = sys.modules.get(name)
    if isinstance(existing, types.ModuleType) and getattr(existing, "__spec__", None):
        return existing
    sys.modules.pop(name, None)
    return importlib.import_module(name)


_real_module("httpx")
_real_module("bs4")
for module_name in (
    "app.services.safe_http",
    "app.services.image_extraction",
    "app.services.content_extractor",
):
    sys.modules.pop(module_name, None)

from app.services import content_extractor  # noqa: E402
from app.services.safe_http import SafeFetchError, SafeFetchResult  # noqa: E402


EXPECTED_TITLE = "City Council Approves Major Transit Funding Plan"
LONG_BODY = "\n\n".join(
    (
        f"Paragraph {index} explains the approved transit funding plan in detail, "
        "including public testimony, budget safeguards, construction milestones, "
        "independent oversight, neighborhood access, and the expected timeline. "
        "Officials described how the proposal developed over several months and "
        "what residents should expect during the next stage of implementation."
    )
    for index in range(1, 11)
) + "."


def _html(
    *,
    title: str = EXPECTED_TITLE,
    canonical_url: str = "https://publisher.example/story",
    body_html: str = "<article><p>Body placeholder.</p></article>",
) -> str:
    return f"""
    <html>
      <head>
        <meta property="og:title" content="{title} | Publisher" />
        <meta property="og:description" content="A concise article summary." />
        <link rel="canonical" href="{canonical_url}" />
      </head>
      <body>{body_html}</body>
    </html>
    """


def _fetched(html: str, url: str = "https://publisher.example/story") -> SafeFetchResult:
    payload = html.encode("utf-8")
    return SafeFetchResult(
        url=url,
        status_code=200,
        headers={"content-type": "text/html; charset=utf-8"},
        content_type="text/html",
        body=payload,
        wire_bytes=len(payload),
        decoded_bytes=len(payload),
        redirect_count=0,
    )


class ContentExtractorContractTests(unittest.IsolatedAsyncioTestCase):
    async def _extract(
        self,
        html: str,
        *,
        expected_title: str | None = EXPECTED_TITLE,
        body: str = LONG_BODY,
        fetched_url: str = "https://publisher.example/story",
        request_url: str = "https://publisher.example/story",
        allowed_domains=None,
    ):
        fetch = AsyncMock(return_value=_fetched(html, fetched_url))
        with patch.object(content_extractor, "safe_fetch", new=fetch), patch.object(
            content_extractor,
            "_extract_best_candidate",
            return_value=(body, "trafilatura"),
        ):
            result = await content_extractor.extract_article_content(
                request_url,
                expected_title=expected_title,
                allowed_domains=allowed_domains,
            )
        return result, fetch

    async def test_complete_requires_positive_identity_and_emits_stable_shape(self):
        result, fetch = await self._extract(_html())

        self.assertEqual(result["content_state"], "complete")
        self.assertEqual(result["completeness"], "complete")
        self.assertGreaterEqual(result["completeness_score"], 0.8)
        self.assertEqual(result["confidence"], result["completeness_score"])
        self.assertTrue(result["identity_valid"])
        self.assertEqual(result["canonical_url"], "https://publisher.example/story")
        self.assertEqual(result["content"], LONG_BODY)
        self.assertEqual(result["partial_content"], "")
        self.assertIsNone(result["retry_after_seconds"])
        self.assertEqual(result["extractor_version"], 4)
        policy = fetch.await_args.kwargs["policy"]
        self.assertEqual(policy.allowed_hosts, frozenset({"publisher.example"}))
        self.assertFalse(policy.allow_subdomains)
        self.assertFalse(fetch.await_args.kwargs.get("follow_redirects", False))

    async def test_long_single_paragraph_excerpt_is_not_called_complete(self):
        excerpt = ("A plausible paywall preview sentence with reporting detail. " * 80).strip()
        result, _fetch = await self._extract(_html(), body=excerpt)

        self.assertGreaterEqual(result["completeness_score"], 0.8)
        self.assertEqual(result["content_state"], "partial")
        self.assertEqual(result["completeness"], "partial")
        self.assertEqual(result["content"], "")
        self.assertEqual(result["partial_content"], excerpt)

    async def test_real_trafilatura_single_newline_paragraphs_can_be_complete(self):
        paragraph = (
            "Residents reviewed the transit proposal with officials, auditors, engineers, "
            "and neighborhood leaders while the council documented funding safeguards, "
            "construction milestones, access commitments, and independent oversight."
        )
        body_html = "<article>" + "".join(
            f"<p>{index}. {paragraph}</p>" for index in range(1, 31)
        ) + "</article>"
        html = _html(body_html=body_html)
        fetch = AsyncMock(return_value=_fetched(html))

        with patch.object(content_extractor, "safe_fetch", new=fetch):
            result = await content_extractor.extract_article_content(
                "https://publisher.example/story",
                expected_title=EXPECTED_TITLE,
            )

        self.assertEqual(result["content_state"], "complete")
        self.assertEqual(result["completeness"], "complete")
        self.assertGreaterEqual(len(result["content"].split("\n\n")), 3)

    async def test_precision_teaser_still_attempts_recall_extraction(self):
        precision_teaser = (
            "The council discussed the transit funding proposal in a preliminary update. "
            * 28
        ).strip()
        self.assertGreaterEqual(content_extractor._word_count(precision_teaser), 180)
        self.assertLess(content_extractor._word_count(precision_teaser), 350)
        html = _html()
        fetch = AsyncMock(return_value=_fetched(html))

        with patch.object(content_extractor, "safe_fetch", new=fetch), patch.object(
            content_extractor.trafilatura,
            "extract",
            side_effect=[precision_teaser, LONG_BODY],
        ) as extract:
            result = await content_extractor.extract_article_content(
                "https://publisher.example/story",
                expected_title=EXPECTED_TITLE,
            )

        self.assertEqual(extract.call_count, 2)
        self.assertEqual(result["extraction_method"], "trafilatura_recall")
        self.assertEqual(result["content_state"], "complete")
        self.assertEqual(result["content"], LONG_BODY)

    async def test_missing_or_placeholder_expected_title_is_never_displayable(self):
        for expected in (None, "", "Latest News", "Article"):
            with self.subTest(expected=expected):
                result, _fetch = await self._extract(
                    _html(),
                    expected_title=expected,
                )
                self.assertFalse(result["identity_valid"])
                self.assertEqual(result["error"], "identity_unverified")
                self.assertEqual(result["failure_class"], "identity_unverified")
                self.assertNotEqual(result["completeness"], "complete")
                self.assertEqual(result["content"], "")
                self.assertEqual(result["partial_content"], LONG_BODY)

    async def test_same_domain_wrong_page_is_rejected(self):
        result, _fetch = await self._extract(
            _html(title="Publisher Account Settings and Billing Dashboard"),
        )

        self.assertFalse(result["identity_valid"])
        self.assertEqual(result["error"], "title_mismatch")
        self.assertEqual(result["failure_class"], "origin_mismatch")
        self.assertEqual(result["content_state"], "identity_mismatch")
        self.assertEqual(result["completeness"], "invalid")
        self.assertEqual(result["content"], "")

    async def test_short_subset_title_cannot_verify_a_generic_topic_page(self):
        cases = (
            (EXPECTED_TITLE, "Transit Funding"),
            ("Election Results: Mayor Wins Historic Third Term", "Election Results"),
        )
        for expected, actual in cases:
            with self.subTest(expected=expected, actual=actual):
                result, _fetch = await self._extract(
                    _html(title=actual),
                    expected_title=expected,
                )

                self.assertLess(result["title_similarity"], 0.45)
                self.assertFalse(result["identity_valid"])
                self.assertEqual(result["error"], "title_mismatch")
                self.assertEqual(result["content_state"], "identity_mismatch")
                self.assertEqual(result["completeness"], "invalid")
                self.assertEqual(result["content"], "")

    async def test_cross_source_canonical_is_rejected(self):
        result, _fetch = await self._extract(
            _html(canonical_url="https://impersonator.example/copied-story"),
        )

        self.assertFalse(result["identity_valid"])
        self.assertEqual(result["error"], "canonical_domain_mismatch")
        self.assertEqual(result["failure_class"], "origin_mismatch")
        self.assertEqual(result["content"], "")

    async def test_implicit_subdomain_redirect_is_not_a_publisher_alias(self):
        result, fetch = await self._extract(
            _html(canonical_url="https://publisher.example/story"),
            fetched_url="https://attacker.publisher.example/copied-story",
            request_url="https://publisher.example/story",
        )

        self.assertFalse(fetch.await_args.kwargs["policy"].allow_subdomains)
        self.assertFalse(result["identity_valid"])
        self.assertEqual(result["error"], "source_domain_mismatch")
        self.assertEqual(result["content"], "")

    async def test_explicit_allowed_domain_supports_known_publisher_redirect(self):
        result, fetch = await self._extract(
            _html(canonical_url="https://canonical.publisher.example/story"),
            fetched_url="https://canonical.publisher.example/story",
            request_url="https://publisher.example/story",
            allowed_domains=["canonical.publisher.example"],
        )

        self.assertTrue(result["identity_valid"])
        self.assertEqual(result["completeness"], "complete")
        policy = fetch.await_args.kwargs["policy"]
        self.assertEqual(
            policy.allowed_hosts,
            frozenset({"publisher.example", "canonical.publisher.example"}),
        )

    async def test_structural_paywall_wins_even_if_hidden_dom_has_long_body(self):
        result, _fetch = await self._extract(
            _html(body_html='<article><div class="paywall">Subscribe</div></article>'),
        )

        self.assertFalse(result["identity_valid"])
        self.assertEqual(result["content_state"], "paywalled")
        self.assertEqual(result["failure_class"], "paywall")
        self.assertEqual(result["completeness"], "invalid")
        self.assertEqual(result["content"], "")

    async def test_teaser_stays_partial_and_never_leaks_through_content(self):
        teaser = (
            "The council met Tuesday and introduced a transit proposal. " * 35
        ) + "Continue reading"
        result, _fetch = await self._extract(_html(), body=teaser)

        self.assertTrue(result["identity_valid"])
        self.assertEqual(result["content_state"], "partial")
        self.assertEqual(result["completeness"], "partial")
        self.assertEqual(result["failure_class"], "incomplete_document")
        self.assertEqual(result["content"], "")
        self.assertEqual(result["partial_content"], teaser)

    async def test_http_retry_after_and_operational_failure_class_are_preserved(self):
        fetch = AsyncMock(
            side_effect=SafeFetchError(
                "http_status",
                url="https://publisher.example/story",
                status_code=429,
                retry_after_seconds=7200,
            )
        )
        with patch.object(content_extractor, "safe_fetch", new=fetch):
            result = await content_extractor.extract_article_content(
                "https://publisher.example/story",
                expected_title=EXPECTED_TITLE,
            )

        self.assertEqual(result["failure_class"], "rate_limited")
        self.assertEqual(result["retry_after_seconds"], 7200)
        self.assertEqual(result["completeness"], "unknown")
        self.assertFalse(result["identity_valid"])
        self.assertEqual(result["content"], "")


if __name__ == "__main__":
    unittest.main()

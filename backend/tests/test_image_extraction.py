import importlib
import os
import re
import sys
import types
import unittest
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class _MiniNode:
    def __init__(self, element):
        self._element = element

    def get(self, key, default=None):
        return self._element.attrib.get(key, default)

    def __getitem__(self, key):
        return self._element.attrib[key]

    @property
    def string(self):
        text = (self._element.text or "").strip()
        return text or None

    def get_text(self):
        return "".join(self._element.itertext())

    def find(self, name=None, attrs=None):
        for element in self._element.iter():
            if element is self._element:
                continue
            if name and element.tag != name:
                continue
            if attrs and any(element.attrib.get(key) != value for key, value in attrs.items()):
                continue
            return _MiniNode(element)
        return None

    def find_all(self, name=None, attrs=None):
        results = []
        for element in self._element.iter():
            if element is self._element:
                continue
            if name and element.tag != name:
                continue
            if attrs and any(element.attrib.get(key) != value for key, value in attrs.items()):
                continue
            results.append(_MiniNode(element))
        return results

    @property
    def body(self):
        return self.find("body")


class _MiniSoup(_MiniNode):
    def __init__(self, html, _parser):
        normalized = re.sub(r"<meta([^>/]*?)>", r"<meta\1 />", html)
        normalized = re.sub(r"<img([^>/]*?)>", r"<img\1 />", normalized)
        root = ET.fromstring(normalized)
        super().__init__(root)


if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.SimpleNamespace(AsyncClient=object)
sys.modules["bs4"] = types.SimpleNamespace(BeautifulSoup=_MiniSoup)
sys.modules.pop("app.services.image_extraction", None)

image_extraction = importlib.import_module("app.services.image_extraction")


class ImageExtractionTests(unittest.TestCase):
    def test_extracts_og_image(self):
        html = """
        <html><head>
        <meta property="og:image" content="https://cdn.example.com/lead.jpg" />
        </head><body></body></html>
        """

        image_url = image_extraction.extract_best_image_from_html(html, "https://example.com/story")

        self.assertEqual(image_url, "https://cdn.example.com/lead.jpg")

    def test_extracts_twitter_image(self):
        html = """
        <html><head>
        <meta name="twitter:image" content="https://cdn.example.com/twitter.jpg" />
        </head><body></body></html>
        """

        image_url = image_extraction.extract_best_image_from_html(html, "https://example.com/story")

        self.assertEqual(image_url, "https://cdn.example.com/twitter.jpg")

    def test_extracts_json_ld_image(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"NewsArticle","image":{"url":"https://cdn.example.com/jsonld.jpg"}}
        </script>
        </head><body></body></html>
        """

        image_url = image_extraction.extract_best_image_from_html(html, "https://example.com/story")

        self.assertEqual(image_url, "https://cdn.example.com/jsonld.jpg")

    def test_resolves_relative_image_url(self):
        html = """
        <html><head>
        <meta property="og:image" content="/images/lead.jpg" />
        </head><body></body></html>
        """

        image_url = image_extraction.extract_best_image_from_html(html, "https://example.com/news/story")

        self.assertEqual(image_url, "https://example.com/images/lead.jpg")

    def test_rejects_logo_and_uses_inline_article_image(self):
        html = """
        <html>
          <head>
            <meta property="og:image" content="https://example.com/assets/logo.png" />
          </head>
          <body>
            <article>
              <img src="/images/story-photo.jpg" width="1200" height="800" alt="Courtroom photo" />
            </article>
          </body>
        </html>
        """

        image_url = image_extraction.extract_best_image_from_html(html, "https://example.com/story")

        self.assertEqual(image_url, "https://example.com/images/story-photo.jpg")


if __name__ == "__main__":
    unittest.main()

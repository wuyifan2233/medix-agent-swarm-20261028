"""Offline search contracts. No network, models, accounts, or live databases."""
import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from research.web_search import SearchResult, WebSearchTool


class SearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_primary_backend_returns_bounded_sources(self):
        engine = Mock()
        engine.text.return_value = [
            {"title": "WHO", "href": "https://www.who.int/example", "body": "public fixture"},
            {"title": "Other", "href": "https://example.org", "body": "fixture"},
        ]
        with patch("research.web_search.DDGS_AVAILABLE", True), patch("research.web_search.DDGS", return_value=engine):
            rows = await WebSearchTool(provider='ddgs').search("public fixture", max_results=1)
        self.assertEqual([(r.title, r.url, r.source) for r in rows], [("WHO", "https://www.who.int/example", "web")])
        self.assertEqual(engine.text.call_count, 1)
        self.assertEqual(engine.text.call_args.kwargs["backend"], "bing")

    async def test_backend_failure_falls_back_without_inventing_results(self):
        engine = Mock()
        engine.text.side_effect = [RuntimeError("backend unavailable"), [{"title": "fixture", "href": "https://example.org", "body": "ok"}]]
        with patch("research.web_search.DDGS_AVAILABLE", True), patch("research.web_search.DDGS", return_value=engine):
            rows = await WebSearchTool(provider='ddgs').search("fixture", max_results=1, retry_count=0)
        self.assertEqual(len(rows), 1)
        self.assertEqual([c.kwargs["backend"] for c in engine.text.call_args_list], ["bing", "duckduckgo"])

    async def test_empty_backends_return_empty_list(self):
        engine = Mock()
        engine.text.return_value = []
        with patch("research.web_search.DDGS_AVAILABLE", True), patch("research.web_search.DDGS", return_value=engine):
            self.assertEqual(await WebSearchTool(provider='ddgs').search("fixture", retry_count=0), [])
        self.assertEqual(engine.text.call_count, 3)

    async def test_all_backend_errors_are_contained(self):
        engine = Mock()
        engine.text.side_effect = RuntimeError("fixture outage")
        with patch("research.web_search.DDGS_AVAILABLE", True), patch("research.web_search.DDGS", return_value=engine):
            self.assertEqual(await WebSearchTool(provider='ddgs').search("fixture", retry_count=0), [])

    async def test_missing_dependency_does_not_call_provider(self):
        with patch("research.web_search.DDGS_AVAILABLE", False), patch("research.web_search.DDGS") as engine:
            self.assertEqual(await WebSearchTool(provider='ddgs').search("fixture"), [])
        engine.assert_not_called()

    async def test_source_enrichment_can_skip_full_page_fetch(self):
        tool = WebSearchTool(provider='ddgs')
        tool.search = AsyncMock(return_value=[SearchResult("fixture", "https://example.org", "summary")])
        tool.fetch_content = AsyncMock()
        rows = await tool.search_with_content("fixture", fetch_full_content=False)
        self.assertIsNone(rows[0]["full_content"])
        tool.fetch_content.assert_not_awaited()

    async def test_full_page_fetch_is_explicit(self):
        tool = WebSearchTool(provider='ddgs')
        tool.search = AsyncMock(return_value=[SearchResult("fixture", "https://example.org", "summary")])
        tool.fetch_content = AsyncMock(return_value="page text")
        rows = await tool.search_with_content("fixture", fetch_full_content=True)
        self.assertEqual(rows[0]["full_content"], "page text")
        tool.fetch_content.assert_awaited_once_with("https://example.org")

    async def test_html_fetch_removes_scripts_and_styles(self):
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, text="<html><style>hidden-css</style><script>hidden-js</script><p>Public fixture text</p></html>")))
        with patch("research.web_search.httpx.AsyncClient", return_value=client):
            text = await WebSearchTool(provider='ddgs').fetch_content("https://example.org")
        self.assertIn("Public fixture text", text)
        self.assertNotIn("hidden-js", text)
        self.assertNotIn("hidden-css", text)

    async def test_page_fetch_timeout_returns_no_content(self):
        def fail(req):
            raise httpx.ReadTimeout("fixture timeout", request=req)
        client = httpx.AsyncClient(transport=httpx.MockTransport(fail))
        with patch("research.web_search.httpx.AsyncClient", return_value=client):
            self.assertIsNone(await WebSearchTool(provider='ddgs').fetch_content("https://example.org"))


if __name__ == "__main__":
    unittest.main()

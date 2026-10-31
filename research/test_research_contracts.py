"""Acceptance regressions for previously reproduced research gaps.

Run explicitly with the other research tests. These checks express required
behaviour; never hide failures as expected successes.
"""
import asyncio
import json
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from core.skill_loader import load_skill_function
from research.evidence_synthesizer import ResearchReport
from research.web_search import SearchResult, WebSearchTool


class AcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_requested_time_window_is_forwarded_to_search_provider(self):
        engine = Mock()
        engine.text.return_value = [{"title": "fixture", "href": "https://example.org", "body": "fixture"}]
        with patch("research.web_search.DDGS_AVAILABLE", True), patch("research.web_search.DDGS", return_value=engine):
            await WebSearchTool(provider='ddgs').search("fixture", timelimit="y", retry_count=0)
        self.assertEqual(engine.text.call_args.kwargs.get("timelimit"), "y")

    async def test_domain_filter_rejects_lookalike_hosts_and_query_strings(self):
        rows = [SearchResult("good", "https://www.who.int/fixture", "fixture"),
                SearchResult("lookalike", "https://who.int.evil.example/fixture", "fixture"),
                SearchResult("query", "https://evil.example/?next=who.int", "fixture")]
        filtered = WebSearchTool(provider='ddgs').filter_by_domain(rows, ["who.int"])
        self.assertEqual([r.title for r in filtered], ["good"])

    async def test_search_allows_other_async_tasks_to_progress(self):
        events = []
        def blocking_search(*args, **kwargs):
            events.append("search-start")
            time.sleep(0.08)
            events.append("search-finish")
            return [{"title": "fixture", "href": "https://example.org", "body": "fixture"}]
        async def heartbeat():
            await asyncio.sleep(0.005)
            events.append("heartbeat")
        engine = Mock()
        engine.text.side_effect = blocking_search
        with patch("research.web_search.DDGS_AVAILABLE", True), patch("research.web_search.DDGS", return_value=engine):
            await asyncio.gather(WebSearchTool(provider='ddgs').search("fixture", retry_count=0), heartbeat())
        self.assertLess(events.index("heartbeat"), events.index("search-finish"))

    async def test_zero_sources_must_not_be_reported_as_completed_research(self):
        function = load_skill_function("deep-research", "research", "deep_research", Path(__file__).resolve().parents[1])
        flow = NS(run=AsyncMock(return_value=ResearchReport("fixture", summary="没有可用来源")))
        with patch("research.deep_research_workflow.DeepResearchWorkflow", return_value=flow):
            result = await function("fixture")
        self.assertNotEqual(result["status"], "completed")

    async def test_synthesis_failure_must_not_be_reported_as_completed_research(self):
        function = load_skill_function("deep-research", "research", "deep_research", Path(__file__).resolve().parents[1])
        from research.evidence_synthesizer import EvidenceSynthesizer
        synth = EvidenceSynthesizer(llm_client=NS(chat=AsyncMock(side_effect=RuntimeError("fixture outage"))))
        report = await synth.synthesize("fixture", [SearchResult("fixture", "https://example.org", "fixture")], [])
        with patch("research.deep_research_workflow.DeepResearchWorkflow", return_value=NS(run=AsyncMock(return_value=report))):
            result = await function("fixture")
        self.assertNotEqual(result["status"], "completed")

    async def test_repeated_source_urls_are_not_counted_as_distinct_evidence(self):
        from research.evidence_synthesizer import EvidenceSynthesizer
        source = SearchResult("WHO fixture", "https://www.who.int/fixture", "fixture")
        report = EvidenceSynthesizer(llm_client=NS())._parse_response(
            "fixture", "【关键发现】\n- fixture\n【综合总结】\nfixture", [source, source], [])
        self.assertEqual(len(report.sources), 1)

    async def test_research_skill_preserves_source_urls_for_the_worker(self):
        function = load_skill_function("deep-research", "research", "deep_research", Path(__file__).resolve().parents[1])
        url = "https://www.who.int/fixture-source"
        report = ResearchReport("fixture", key_findings=["fixture"], summary="fixture",
                                sources=[{"type": "web", "title": "WHO fixture", "url": url}])
        with patch("research.deep_research_workflow.DeepResearchWorkflow", return_value=NS(run=AsyncMock(return_value=report))):
            result = await function("fixture")
        self.assertIn(url, json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()

"""ResearchAgent tools and evidence flow with isolated, deterministic fixtures."""
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from core.skill_loader import load_skill_function
from core.llm_client import LLMResponse, ToolCall
from research.deep_research_workflow import DeepResearchWorkflow
from research.evidence_synthesizer import EvidenceSynthesizer, ResearchReport
from research.web_search import SearchResult

ROOT = Path(__file__).resolve().parents[1]


class ResearchTests(unittest.IsolatedAsyncioTestCase):
    def workflow(self):
        kb = NS(search=Mock(return_value=[]))
        with patch("research.deep_research_workflow.get_knowledge_base", return_value=kb):
            flow = DeepResearchWorkflow(llm_client=NS(chat=AsyncMock()))
        return flow

    async def test_research_worker_exposes_search_tools_but_not_ui_runtime(self):
        from agents.research_agent import ResearchAgent
        worker = ResearchAgent(llm_client=NS())
        names = {t["function"]["name"] for t in worker.get_tools_for_llm()}
        self.assertTrue({"deep_research", "clinical_guideline", "search_knowledge"} <= names)
        self.assertTrue(names.isdisjoint({"tts_voice", "voice_input", "scheduled_reminder"}))

    async def test_worker_executes_requested_research_then_receives_tool_result(self):
        import json
        from agents.research_agent import ResearchAgent
        messages = []
        async def reply(**kwargs):
            messages.append(list(kwargs["messages"]))
            if len(messages) == 1:
                return LLMResponse(None, [ToolCall("fixture-call", "deep_research", {"query": "public fixture"})], "tool_calls")
            return LLMResponse("检索结果来自 WHO fixture。", [], "stop")
        llm = NS(chat_with_tools=reply, create_tool_message=lambda **kw: {"role": "tool", "tool_call_id": kw["tool_call_id"], "content": json.dumps(kw["result"])})
        worker = ResearchAgent(llm_client=llm)
        worker.loop.validator = None
        with patch.object(worker.skill_registry, "execute", new=AsyncMock(return_value={"answer": "WHO fixture", "status": "completed"})) as execute:
            result = await worker.process({"question": "请联网研究这个公开问题"})
        execute.assert_awaited_once_with("deep_research", query="public fixture")
        self.assertIn("WHO", result["answer"])
        self.assertTrue(any(m["role"] == "tool" and "WHO" in m["content"] for m in messages[1]))

    async def test_guideline_tool_only_uses_local_guideline_category(self):
        function = load_skill_function("clinical-guideline", "guideline", "clinical_guideline", ROOT)
        kb = NS(search=Mock(return_value=[{"score": 0.9, "content": "fixture", "metadata": {"disease": "fixture", "organization": "fixture", "year": "2026"}}]))
        with patch.dict(function.__globals__, {"_kb_instance": kb}):
            result = await function("fixture")
        self.assertEqual(result["source"], "向量数据库")
        self.assertEqual(kb.search.call_args.kwargs["filter_type"], "clinical_guideline")

    async def test_network_and_local_results_both_reach_synthesis(self):
        flow = self.workflow()
        flow._plan_queries = AsyncMock(return_value=["public fixture query"])
        web = [SearchResult("WHO fixture", "https://www.who.int/fixture", "fixture")]
        local = [{"id": "local-1", "content": "local fixture", "metadata": {"title": "local"}, "score": 0.7}]
        flow.web_search.search = AsyncMock(return_value=web)
        flow.knowledge_base.search.return_value = local
        report = ResearchReport(query="fixture", key_findings=["fixture"], summary="fixture")
        flow.synthesizer.synthesize = AsyncMock(return_value=report)
        self.assertIs(await flow.run("fixture"), report)
        args = flow.synthesizer.synthesize.call_args.kwargs
        self.assertEqual(args["web_results"], web)
        self.assertEqual(args["kb_results"], local)

    async def test_local_search_outage_does_not_discard_network_results(self):
        flow = self.workflow()
        flow._plan_queries = AsyncMock(return_value=["public fixture query"])
        flow.web_search.search = AsyncMock(return_value=[SearchResult("WHO fixture", "https://www.who.int/fixture", "fixture")])
        flow.knowledge_base.search.side_effect = RuntimeError("fixture local outage")
        flow.synthesizer.synthesize = AsyncMock(return_value=ResearchReport("fixture"))
        await flow.run("fixture")
        args = flow.synthesizer.synthesize.call_args.kwargs
        self.assertEqual(len(args["web_results"]), 1)
        self.assertEqual(args["kb_results"], [])

    async def test_planning_failure_falls_back_to_original_question(self):
        flow = self.workflow()
        flow.llm_client.chat.side_effect = RuntimeError("fixture planning outage")
        self.assertEqual(await flow._plan_queries("public fixture question"), ["public fixture question"])

    async def test_source_metadata_comes_from_retrieved_inputs(self):
        synth = EvidenceSynthesizer(llm_client=NS())
        web = [SearchResult("WHO fixture", "https://www.who.int/fixture", "fixture")]
        report = synth._parse_response("fixture", "【关键发现】\n- fixture\n【证据等级】\nC\n【综合总结】\nfixture\n【建议】\n- fixture", web, [])
        self.assertEqual(report.sources, [{"type": "web", "title": "WHO fixture", "url": "https://www.who.int/fixture"}])

    async def test_deep_research_skill_uses_real_workflow_report_contract(self):
        function = load_skill_function("deep-research", "research", "deep_research", ROOT)
        report = ResearchReport("fixture", key_findings=["fixture"], sources=[{"type": "web", "title": "fixture", "url": "https://example.org"}], confidence=0.5, summary="fixture")
        flow = NS(run=AsyncMock(return_value=report))
        with patch("research.deep_research_workflow.DeepResearchWorkflow", return_value=flow):
            result = await function("fixture", max_iterations=1)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["sources"], 1)
        self.assertEqual(flow.run.call_args.kwargs["max_web_results"], 5)


if __name__ == "__main__":
    unittest.main()

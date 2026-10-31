"""Opt-in public-query checks. Model checks use configured credentials and quota.

Every check runs in a bounded subprocess. No account, chat, wallet, or Mem0 is used.
The web-only workflow uses its existing use_knowledge_base=False option; it does
not certify the default Milvus-backed production path.
"""
import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
QUERIES = ["WHO hypertension fact sheet", "高血压 世界卫生组织 事实清单", "site:who.int hypertension fact sheet"]
ROUTES = [
    ("simple", "请用三条简短建议说明如何做好日常作息记录。", {"consultation_agent"}),
    ("research", "请联网检索世界卫生组织关于高血压的公开官方资料，只核对来源和发布日期，不做个人诊断。", {"research_agent"}),
    ("collaboration", "这是虚构演示案例：有高血压病史的人反复头痛、头晕且睡眠不好。请分别完成症状关联与风险分析、官方指南证据检索、日常管理建议，最后整合。", {"research_agent", "diagnostic_agent", "consultation_agent"}),
]


def model_client():
    from core.llm_client import LLMClient
    client = LLMClient()
    client.max_tokens = 900
    defaults = dict(client.request_defaults)
    defaults["extra_body"] = {**defaults.get("extra_body", {}), "thinking": {"type": "disabled"}}
    client.request_defaults = defaults
    client.client = client.client.with_options(timeout=30, max_retries=0)
    return client


async def child_check(name):
    if name.startswith("search-"):
        from research.web_search import WebSearchTool
        query = QUERIES[int(name.rsplit("-", 1)[1])]
        rows = await WebSearchTool().search(query, max_results=3, retry_count=0)
        return {"status": "passed" if rows else "failed", "query": query,
                "result_count": len(rows), "sources": [asdict(row) for row in rows]}
    client = model_client()
    try:
        if name == "routes":
            from swarm.lead_agent import LeadAgent
            lead = LeadAgent(llm_client=client)
            cases = []
            for ident, question, expected in ROUTES:
                result = await lead.assess_and_decompose(question)
                agents = {task.get("assigned_agent") for task in result.get("subtasks", [])}
                cases.append({"case": ident, "question": question, "expected_agents": sorted(expected),
                              "actual_agents": sorted(str(agent) for agent in agents),
                              "status": "passed" if expected <= agents else "failed",
                              "subtasks": result.get("subtasks", [])})
            return {"status": "passed" if all(row["status"] == "passed" for row in cases) else "failed",
                    "cases": cases, "model_requests": len(cases)}
        from research.deep_research_workflow import DeepResearchWorkflow
        flow = DeepResearchWorkflow(llm_client=client, use_knowledge_base=False)
        original = flow.web_search.search
        searches = []
        async def traced_search(query, **kwargs):
            kwargs["retry_count"] = 0
            rows = await original(query, **kwargs)
            searches.append({"query": query, "sources": [asdict(row) for row in rows]})
            return rows
        flow.web_search.search = traced_search
        report = await flow.run("查找世界卫生组织关于高血压的公开事实清单，说明资料涉及哪些主题并列出实际来源，不提供个体诊疗建议。", max_web_results=6, max_kb_results=0)
        actual_urls = {row["url"] for search in searches for row in search["sources"]}
        passed = bool(report.sources and report.summary and report.key_findings) and not report.summary.startswith("综合失败")
        passed = passed and all(row.get("url") in actual_urls for row in report.sources if row.get("type") == "web")
        return {"status": "passed" if passed else "failed", "scope": "real model + real web search, local KB explicitly disabled",
                "searches": searches, "report": asdict(report), "model_requests": 2}
    finally:
        await client.client.close()


def run_bounded(name):
    started = time.monotonic()
    timeout = 90 if name == "workflow" else 65 if name == "routes" else 35
    try:
        process = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child", name],
                                 capture_output=True, text=True, timeout=timeout)
        if process.returncode:
            result = {"status": "error", "error_type": "ChildProcessFailure", "exit_code": process.returncode}
        else:
            result = json.loads(process.stdout)
    except subprocess.TimeoutExpired:
        result = {"status": "timeout", "timeout_seconds": timeout}
    except (ValueError, OSError) as exc:
        result = {"status": "error", "error_type": type(exc).__name__}
    return {"case": name, "elapsed_seconds": round(time.monotonic() - started, 3), **result}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", choices=["search-0", "search-1", "search-2", "routes", "workflow"], help=argparse.SUPPRESS)
    parser.add_argument("--with-model", action="store_true", help="Opt in to up to five short model calls")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    from loguru import logger
    logger.remove()
    if args.child:
        try:
            result = asyncio.run(child_check(args.child))
        except Exception as exc:
            result = {"status": "error", "error_type": type(exc).__name__, "http_status": getattr(exc, "status_code", None)}
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0
    cases = ["search-0", "search-1", "search-2"] + (["routes", "workflow"] if args.with_model else [])
    with TemporaryDirectory(prefix="medix-public-research-") as directory:
        os.environ.update(MEDIX_DATA_DIR=directory, MEDIX_DATABASE_URL="sqlite:///" + str(Path(directory) / "app.db"),
                          MEDIX_IDENTITY_NAMESPACE="research-public-check")
        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(run_bounded, cases))
    report = {"model_tests_enabled": args.with_model, "uses_private_data": False, "cases": results}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    for row in results:
        print(json.dumps({k: row[k] for k in ("case", "status", "elapsed_seconds")}, ensure_ascii=False))
    return 0 if all(row["status"] == "passed" for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

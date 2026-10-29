"""Non-training runtime checks. Reads OPENAI_API_KEY; never persists credentials."""
import asyncio, json, os, sys, time, traceback
from pathlib import Path
os.chdir(Path(__file__).resolve().parent)
sys.path.insert(0, str(Path.cwd()))
from loguru import logger
logger.remove()
logger.add(sys.stderr, level="WARNING")

async def main():
    import examples.test_all as tests
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    results=[]
    async def check(name, func, timeout=120):
        started=time.monotonic()
        try:
            result=await asyncio.wait_for(func(), timeout)
            if result is False:
                raise AssertionError("Check returned False")
            row={"check":name,"status":"passed","seconds":round(time.monotonic()-started,2)}
            if result is not None: row["result"]=result
        except Exception as exc:
            row={"check":name,"status":"failed","error":str(exc),"seconds":round(time.monotonic()-started,2)}
        results.append(row)
        print(json.dumps(row,ensure_ascii=False),flush=True)
    mode=sys.argv[1] if len(sys.argv)>1 else "offline"
    if mode=="offline":
        for name in ["test_shared_context","test_agent_capabilities","test_agent_identity","test_short_term_memory","test_harness_constraint_validator","test_harness_auto_fixer","test_harness_entropy_manager"]:
            await check(name,getattr(tests,name),30)
    elif mode=="api":
        for name in ["test_agent_loop_simple_question","test_agent_loop_with_tools","test_simple_routing","test_complex_case_swarm"]:
            await check(name,getattr(tests,name),180)
    elif mode.startswith("test_"):
        await check(mode,getattr(tests,mode),240)
    elif mode=="full":
        import ast
        tree=ast.parse(Path("examples/test_all.py").read_text(encoding="utf-8"))
        main_node=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=="main")
        assignment=next(n for n in main_node.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="tests" for t in n.targets))
        for entry in assignment.value.elts:
            name=entry.elts[1].id
            if name=="test_long_term_memory":
                results.append({"check":name,"status":"skipped","reason":"No Mem0 key supplied"})
                continue
            await check(name,getattr(tests,name),240)
    elif mode=="kb":
        async def query():
            from knowledge.milvus_kb import MedicalKnowledgeBase
            kb=MedicalKnowledgeBase()
            hits=kb.search("高血压",top_k=3)
            assert hits, "Knowledge base returned no results"
            filtered=kb.search("高血压",top_k=3,filter_type="clinical_guideline")
            assert filtered, "Filtered knowledge query returned no results"
            assert all(row["metadata"]["type"]=="clinical_guideline" for row in filtered)
            assert all(-1.001 <= row["score"] <= 1.001 for row in hits+filtered)
            assert kb.count_documents()==180
            return {"hits":len(hits),"filtered_hits":len(filtered),"stored_rows":kb.count_documents()}
        await check("knowledge_base_real_search",query,180)
    elif mode=="regression":
        async def dedup():
            from memory.entropy_manager import MemoryEntropyManager
            rows=[{"content":"case A"},{"content":"case A"},{"content":"case B"}]
            result=MemoryEntropyManager().deduplicate_sessions(rows)
            assert [row["content"] for row in result]==["case A","case B"]
            return {"distinct_cases":len(result)}
        await check("memory_distinct_cases_preserved",dedup)
        async def parse_report():
            from research.evidence_synthesizer import EvidenceSynthesizer
            from core import LLMClient
            text="【关键发现】\n1. First finding\n2. Second finding\n【证据等级】C级\n【置信度】0.5\n【信息冲突】无\n【综合总结】Summary\n【建议】\n1. First recommendation"
            report=EvidenceSynthesizer(LLMClient())._parse_response("test",text,[],[])
            assert report.key_findings==["First finding","Second finding"]
            assert report.recommendations==["First recommendation"]
            return {"numbered_findings":len(report.key_findings)}
        await check("numbered_research_findings_parsed",parse_report)
    elif mode=="research":
        async def research():
            from research.deep_research_workflow import DeepResearchWorkflow
            report=await DeepResearchWorkflow().run("高血压诊疗指南与生活方式管理",max_web_results=3,max_kb_results=3)
            assert report.key_findings and report.summary
            assert any(source["type"]=="knowledge_base" for source in report.sources)
            return {"findings":len(report.key_findings),"web_sources":sum(s["type"]=="web" for s in report.sources),"kb_sources":sum(s["type"]=="knowledge_base" for s in report.sources)}
        await check("deep_research_real_sources",research,240)
    elif mode=="skills":
        from core.skill_loader import load_skill_function
        async def knowledge_skill():
            fn=load_skill_function("search-knowledge","search","search_knowledge")
            result=await fn("高血压",max_results=3)
            assert result["total_found"]==3
            return {"total_found":result["total_found"]}
        await check("search_knowledge_real_results",knowledge_skill)
        for directory,script,name,args in [
            ("recommend-lifestyle","lifestyle","recommend_lifestyle",{"diagnosis":"高血压"}),
            ("disease-code","code","disease_code",{"disease_name":"2型糖尿病"}),
            ("clinical-guideline","guideline","clinical_guideline",{"query":"高血压"}),
        ]:
            async def skill(directory=directory,script=script,name=name,args=args):
                result=await load_skill_function(directory,script,name)(**args)
                assert result.get("source")=="向量数据库",result
                assert result["answer"]
                return {"source":result["source"],"answer_chars":len(result["answer"])}
            await check(name+"_real_retrieval",skill)
    Path("verification_"+mode+".json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    return int(any(r["status"]=="failed" for r in results))
if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))

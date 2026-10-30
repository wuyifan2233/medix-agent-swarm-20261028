import base64
import io
import unittest
from fastapi.testclient import TestClient
from PIL import Image
from web.app import app, jobs, normalize_image

class WebBoundaryTests(unittest.TestCase):
    def test_chat_always_uses_model_controlled_memory_without_client_toggle(self):
        import uuid
        import config
        from unittest.mock import patch
        from web.app import health
        with patch.dict(health,knowledge='ready'),patch.dict(config.LLM_CONFIG,api_key='synthetic'),patch('web.app.executor.submit') as submit:
            for extra in ({},{'remember':False,'patient':'self'}):
                response=TestClient(app).post('/api/chat',json={'chat_id':str(uuid.uuid4()),'message':'虚构测试：我妈妈最近鼻塞',**extra})
                self.assertEqual(response.status_code,202,response.text)
                payload=submit.call_args.args[2]
                self.assertTrue(payload['remember'])
                self.assertEqual(payload['patient'],'auto')
                jobs.pop(response.json()['job_id'],None)

    def test_image_pixels_are_reencoded(self):
        stream = io.BytesIO()
        Image.new("RGB", (32, 20), "white").save(stream, "PNG")
        result = normalize_image({"data": "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()})
        self.assertTrue(result.startswith("data:image/jpeg;base64,"))
        image = Image.open(io.BytesIO(base64.b64decode(result.split(",", 1)[1])))
        self.assertEqual(image.size, (32, 20))

    def test_disguised_non_image_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_image({"data": "data:image/png;base64," + base64.b64encode(b"<script>alert(1)</script>").decode()})

    def test_svg_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_image({"data": "data:image/svg+xml;base64,PHN2Zz4="})

    def test_empty_message_is_rejected(self):
        client = TestClient(app)
        self.assertEqual(client.post("/api/chat", json={"message": "", "images": []}).status_code, 400)

    def test_foreign_origin_is_rejected(self):
        client = TestClient(app)
        self.assertEqual(client.post("/api/chat", json={}, headers={"Origin":"https://elsewhere.example"}).status_code, 403)

    def test_other_browser_cannot_read_job(self):
        jobs["boundary-test"] = {"owner": "a" * 32, "status": "completed"}
        try:
            client = TestClient(app)
            self.assertEqual(client.get("/api/jobs/boundary-test").status_code, 404)
            client.cookies.clear()
            client.cookies.set("medix_browser", "a" * 32)
            self.assertEqual(client.get("/api/jobs/boundary-test").status_code, 200)
        finally:
            jobs.pop("boundary-test", None)

class ReadinessTests(unittest.TestCase):
    def test_auth_failure_has_safe_actionable_message(self):
        from unittest.mock import patch, AsyncMock
        from web.app import health, run_job
        error = RuntimeError("do-not-expose-provider-response")
        error.status_code = 401
        job = {}
        with patch.dict(health, knowledge="ready"), patch("web.app.analyze", new=AsyncMock(side_effect=error)):
            run_job(job, {}, "synthetic-session", "synthetic-user")
        self.assertEqual(job["status"], "failed")
        self.assertIn("LOCAL_API_KEY", job["error"])
        self.assertNotIn("do-not-expose", job["error"])

    def test_page_opens_without_keys(self):
        from unittest.mock import patch
        import config
        with patch.dict(config.LLM_CONFIG, api_key=""), patch.dict(config.MEM0_CONFIG, api_key=""):
            client = TestClient(app)
            self.assertEqual(client.get("/").status_code, 200)
            status = client.get("/api/health")
            self.assertEqual(status.status_code, 200)
            self.assertFalse(status.json()["model_configured"])
            self.assertFalse(status.json()["memory_configured"])
            self.assertEqual(status.json()["memory_backend"], "mem0")


    def test_invalid_chat_id_returns_400(self):
        client = TestClient(app)
        for value in (None, 1, [], {}):
            response = client.post("/api/chat", json={"message": "合成测试", "chat_id": value})
            self.assertEqual(response.status_code, 400)

    def test_unready_service_does_not_enqueue(self):
        from unittest.mock import patch
        from web.app import health
        import config
        import uuid
        client = TestClient(app)
        before = len(jobs)
        for state in ("loading", "error"):
            with patch.dict(health, {"knowledge": state}), patch.dict(config.LLM_CONFIG, {"api_key": "synthetic-key"}):
                response = client.post("/api/chat", json={"message": "合成测试", "chat_id": str(uuid.uuid4())})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(len(jobs), before)

    def test_missing_key_does_not_enqueue(self):
        from unittest.mock import patch
        from web.app import health
        import config
        import uuid
        with patch.dict(health, {"knowledge": "ready"}), patch.dict(config.LLM_CONFIG, {"api_key": ""}):
            response = TestClient(app).post("/api/chat", json={"message": "合成测试", "chat_id": str(uuid.uuid4())})
            self.assertEqual(response.status_code, 503)

class SwarmContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_subtask_keeps_image_facts_and_session(self):
        from types import SimpleNamespace
        from agents.base_agent import BaseAgent
        class CaptureAgent(BaseAgent):
            def get_system_prompt(self): return "test"
            def register_tools(self): pass
            async def run_loop(self, input_data): return input_data
        agent = CaptureAgent("context-test", {}, llm_client=object())
        agent.shared_context = SimpleNamespace(session_id="image-session", data={
            "original_question":"第二次记录为 136/88 mmHg", "request_context":{"image":True}})
        data = await agent.process_subtask(SimpleNamespace(id="one", type="read", description="读取第二次记录"))
        self.assertIn("136/88", data["question"])
        self.assertEqual(data["session_id"], "image-session")
        self.assertTrue(data["context"]["image"])

if __name__ == "__main__":
    unittest.main()

class OriginalSourceTests(unittest.TestCase):
    def test_knowledge_original_document_and_path_boundary(self):
        from web.app import ROOT
        client = TestClient(app)
        name = '01_lifestyle_hypertension.txt'
        response = client.get('/api/knowledge/source/' + name)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['title'],'高血压生活方式建议')
        self.assertEqual(response.json()['content'], (ROOT / 'knowledge/data/documents' / name).read_text(encoding='utf-8'))
        for filename in ['config.py', 'missing.txt', '%2E%2E%2Fconfig.py']:
            self.assertEqual(client.get('/api/knowledge/source/' + filename).status_code, 404)

    def test_document_title_does_not_depend_on_chunk_start(self):
        from web.app import knowledge_title
        self.assertEqual(knowledge_title('05_symptoms_emergency.txt'),'急症症状识别与处理')
        self.assertEqual(knowledge_title('11_icd10_endocrine.txt'),'内分泌、营养和代谢疾病 ICD-10 编码')
        self.assertEqual(knowledge_title('missing.txt'),'missing.txt')
        for invalid in (None,'','../config.py','../05_symptoms_emergency.txt'):
            self.assertEqual(knowledge_title(invalid),'本地医学资料')

    def test_personal_and_family_memory_are_separate_and_owner_scoped(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from memory.case_memory import CaseMemory
        with tempfile.TemporaryDirectory() as directory:
            store = CaseMemory(Path(directory) / 'cases.db')
            client = TestClient(app)
            client.cookies.set('medix_browser', 'a'*32)
            owner = 'web-' + 'a'*32
            store.save(owner, 'self-session', '我最近头晕', 'self')
            store.save(owner, 'father-session', '我父亲最近头晕', 'father')
            store.save(owner, 'mother-session', '我母亲最近头痛', 'mother')
            store.save('web-other', 'other-session', '我父亲最近咳嗽', 'father')
            with patch('web.app.case_memory', store), patch('web.app.WebMem0Memory', return_value=store):
                personal = client.get('/api/memories?scope=self').json()['memories']
                family = client.get('/api/memories?scope=family').json()['memories']
                self.assertEqual([row['patient'] for row in personal], ['self'])
                self.assertEqual({row['patient'] for row in family}, {'father', 'mother'})
                self.assertEqual(len(family), 2)
                self.assertEqual(client.get('/api/memories?scope=invalid').status_code, 400)


class ReferenceFocusTests(unittest.TestCase):
    def test_focus_is_verbatim_relevant_paragraph_inside_model_context(self):
        from web.app import reference_focus
        content = "高血压生活方式建议\n\n1. 低盐饮食\n每日钠摄入小于2g，减少腌制品和加工肉类。\n\n2. 有氧运动\n每周安排适度运动，避免突然增加运动量。"
        focus = reference_focus(content, "高血压的日常低盐饮食有哪些注意事项？请结合本地资料简短回答。")
        self.assertIn("低盐饮食", focus)
        self.assertNotIn("有氧运动", focus)
        self.assertIn(focus, content[:750])
        self.assertEqual(reference_focus(content, "完全不相关"), content[:750])

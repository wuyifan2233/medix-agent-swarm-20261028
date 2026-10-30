import os
os.environ.setdefault("MEDIX_WECHAT_DISABLE", "1")
os.environ.setdefault("MEDIX_QQ_DISABLE", "1")
import base64
import io
import unittest
from fastapi.testclient import TestClient
from PIL import Image
from web.app import app, jobs, normalize_image

class WebBoundaryTests(unittest.TestCase):
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

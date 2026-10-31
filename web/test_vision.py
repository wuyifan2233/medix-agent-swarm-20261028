import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from web.vision import read_images

class VisionTests(unittest.IsolatedAsyncioTestCase):
    def client(self, responses, url="https://api.deepseek.com/v1"):
        create=AsyncMock(side_effect=responses)
        return SimpleNamespace(config={"base_url":url},model_name="deepseek-flash",
            client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    def response(self, content, reason="stop"):
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason=reason,message=SimpleNamespace(content=content))])
    async def test_pixels_and_transcription_budget(self):
        client=self.client([self.response("UA 480; TBIL 26.3; DBIL 10.4")])
        result=await read_images(client,["data:image/png;base64,test"],"解读报告")
        self.assertIn("480",result)
        args=client.client.chat.completions.create.call_args.kwargs
        self.assertEqual(args["extra_body"],{"thinking":{"type":"disabled"}})
        self.assertEqual(args["max_tokens"],4096)
        self.assertEqual(args["messages"][1]["content"][1]["image_url"]["url"],"data:image/png;base64,test")
    async def test_truncated_read_is_retried_not_used(self):
        client=self.client([self.response("只有标题","length"),self.response("UA 480")])
        self.assertEqual(await read_images(client,["image"],"问题"),"UA 480")
        self.assertEqual(client.client.chat.completions.create.call_args.kwargs["max_tokens"],8192)
    async def test_incomplete_or_empty_read_is_reported(self):
        for responses in [[self.response("开头","length"),self.response("仍不完整","length")],[self.response("")],[self.response("blocked","content_filter")]]:
            with self.assertRaises(ValueError):await read_images(self.client(responses),["image"],"问题")
    async def test_other_provider_does_not_receive_deepseek_option(self):
        client=self.client([self.response("已读取")],"https://example.com/v1")
        await read_images(client,["image"],"问题")
        self.assertNotIn("extra_body",client.client.chat.completions.create.call_args.kwargs)

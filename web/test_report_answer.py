import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from web.report_answer import contradicts_report, ensure_report_answer, FALLBACK

class ReportAnswerTests(unittest.IsolatedAsyncioTestCase):
    def test_absent_material(self):
        for text in ('这次没有收到图片或文字资料', '我暂时还看不到您说的“病历”具体内容', '未收到您上传的图片', '没有提供报告内容'):
            with self.subTest(text=text): self.assertTrue(contradicts_report(text))

    def test_legitimate_uncertainty(self):
        for text in ('没有看到其他日期的同类报告', '图片中的日期看不清', '报告是谁的还不明确', '没有收到既往报告', '没有提供症状和用药史', '无法确认某项数值', '已读取21项结果'):
            with self.subTest(text=text): self.assertFalse(contradicts_report(text))

    async def test_valid_does_not_call_model(self):
        with patch('web.report_answer.LLMClient') as factory:
            self.assertEqual(await ensure_report_answer('已读取报告', 'facts'), ('已读取报告', 'verified'))
            factory.assert_not_called()

    async def test_retry_once_and_keep_evidence(self):
        client=SimpleNamespace(chat=AsyncMock(), client=SimpleNamespace(close=AsyncMock()));client.chat.return_value={'content':'尿酸480，日期待核实','finish_reason':'stop'}
        with patch('web.report_answer.LLMClient',return_value=client):
            self.assertEqual(await ensure_report_answer('没有收到图片','报告事实'),('尿酸480，日期待核实','repaired'))
        client.chat.assert_awaited_once();client.client.close.assert_awaited_once()
        self.assertEqual(client.chat.call_args.args[0][1]['content'],'报告事实')

    async def test_bad_retry_and_truncation_fail_closed(self):
        for result in ({'content':'没有收到图片','finish_reason':'stop'}, {'content':'部分回答','finish_reason':'length'}):
            client=SimpleNamespace(chat=AsyncMock(), client=SimpleNamespace(close=AsyncMock()));client.chat.return_value=result
            with patch('web.report_answer.LLMClient',return_value=client):
                self.assertEqual(await ensure_report_answer('没有收到图片','facts'),(FALLBACK,'failed'))
            client.chat.assert_awaited_once()

    async def test_provider_error(self):
        client=SimpleNamespace(chat=AsyncMock(), client=SimpleNamespace(close=AsyncMock()));client.chat.side_effect=RuntimeError('unavailable')
        with patch('web.report_answer.LLMClient',return_value=client):
            self.assertEqual(await ensure_report_answer('没有收到图片','facts'),(FALLBACK,'failed'))
        client.client.close.assert_awaited_once()

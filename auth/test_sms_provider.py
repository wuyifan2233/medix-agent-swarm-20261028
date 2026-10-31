import unittest
import os
from types import SimpleNamespace
from unittest.mock import Mock, patch
from fastapi import HTTPException
from auth.sms_provider import AliyunSms


class SmsProviderTests(unittest.TestCase):
    def test_placeholder_keys_do_not_enable_sms(self):
        with patch.dict(os.environ,{'MEDIX_SMS_ACCESS_KEY_ID':'xxx','MEDIX_SMS_ACCESS_KEY_SECRET':'xxx','MEDIX_SMS_SIGN_NAME':'xxx'}):
            self.assertFalse(AliyunSms().configured())

    def test_only_pass_is_accepted_not_just_ok(self):
        provider = AliyunSms()
        client = Mock()
        with patch.object(provider, "_client", return_value=client):
            client.check_sms_verify_code.return_value.body = SimpleNamespace(code="OK", success=True,
                model=SimpleNamespace(verify_result="UNKNOWN"))
            self.assertFalse(provider.verify("13800000001", "medix-login", "123456"))
            client.check_sms_verify_code.return_value.body.model.verify_result = "PASS"
            self.assertTrue(provider.verify("13800000001", "medix-login", "123456"))

    def test_send_uses_generated_codes_and_does_not_return_them(self):
        provider = AliyunSms()
        client = Mock()
        client.send_sms_verify_code.return_value.body = SimpleNamespace(code="OK", success=True)
        with patch.object(provider, "_client", return_value=client):
            provider.send("13800000001", "medix-login")
        request = client.send_sms_verify_code.call_args.args[0]
        self.assertFalse(request.return_verify_code)
        self.assertEqual(request.code_length, 6)
        self.assertEqual(request.valid_time, 300)
        self.assertEqual(request.scheme_name, "medix-login")
        self.assertIn("##code##", request.template_param)

    def test_provider_exception_does_not_disclose_keys_or_phone(self):
        provider = AliyunSms()
        with patch.object(provider, "_client", side_effect=RuntimeError("secret-key-with-phone")):
            with self.assertRaises(HTTPException) as error:
                provider.send("13800000001", "medix-login")
            self.assertNotIn("secret-key", error.exception.detail)

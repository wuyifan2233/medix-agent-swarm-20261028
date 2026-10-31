"""Aliyun PNVS only. No development bypass or plaintext code storage."""
import json
import os
from fastapi import HTTPException


class AliyunSms:
    def configured(self):
        return all(os.getenv(key, "").strip().lower() not in {"", "xxx"} for key in ("MEDIX_SMS_ACCESS_KEY_ID", "MEDIX_SMS_ACCESS_KEY_SECRET", "MEDIX_SMS_SIGN_NAME"))

    def _client(self):
        if not self.configured():
            raise HTTPException(503, "短信登录暂未配置，请使用账号密码登录。")
        from alibabacloud_dypnsapi20170525.client import Client
        from alibabacloud_tea_openapi.models import Config
        return Client(Config(access_key_id=os.environ["MEDIX_SMS_ACCESS_KEY_ID"],
            access_key_secret=os.environ["MEDIX_SMS_ACCESS_KEY_SECRET"],
            endpoint="dypnsapi.aliyuncs.com", region_id="cn-hangzhou", read_timeout=8000, connect_timeout=5000))

    def send(self, phone, scheme):
        from alibabacloud_dypnsapi20170525.models import SendSmsVerifyCodeRequest
        try:
            body = self._client().send_sms_verify_code(SendSmsVerifyCodeRequest(
                phone_number=phone, country_code="86", scheme_name=scheme,
                sign_name=os.getenv("MEDIX_SMS_SIGN_NAME"), template_code=os.getenv("MEDIX_SMS_TEMPLATE_CODE", "100001"),
                template_param=json.dumps({"code":"##code##", "min":"5"}),
                code_length=6, code_type=1, valid_time=300, interval=60, duplicate_policy=1,
                return_verify_code=False)).body
            if body.code != "OK" or body.success is not True:
                raise HTTPException(502, "短信发送失败，请检查服务配置、余额或稍后重试。")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(502, "短信服务暂时不可用，请稍后重试。") from None

    def verify(self, phone, scheme, code):
        from alibabacloud_dypnsapi20170525.models import CheckSmsVerifyCodeRequest
        try:
            body = self._client().check_sms_verify_code(CheckSmsVerifyCodeRequest(
                phone_number=phone, country_code="86", scheme_name=scheme, verify_code=code)).body
            if body.code != "OK" or body.success is not True:
                raise HTTPException(502, "验证码核验服务暂时不可用，请稍后重试。")
            return body.model is not None and body.model.verify_result == "PASS"
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(502, "验证码核验服务暂时不可用，请稍后重试。") from None

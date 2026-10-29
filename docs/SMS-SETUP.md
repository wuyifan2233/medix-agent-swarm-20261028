# 本地手机号登录

## 创建并配置服务凭据

1. 用主账号进入阿里云 RAM 控制台，创建专用于本项目的 RAM 用户（例如 `medix-sms`）。不需要控制台登录权限。
2. 在 RAM 的「权限策略」中创建自定义策略，使用同目录 `ALIYUN-SMS-POLICY.json` 的内容。将该策略授权给这个 RAM 用户，只允许发送、核验短信。
3. 为这个 RAM 用户创建 AccessKey。密钥只在本机保管，不要发到聊天或提交到 Git；不要使用主账号 AccessKey。
4. 将以下内容填写到项目根目录 `.env.sms`（已忽略）。`MEDIX_SMS_SIGN_NAME` 填短信认证控制台赠送签名的实际名称。

```dotenv
MEDIX_SMS_ACCESS_KEY_ID=填写你的RAM用户AccessKeyId
MEDIX_SMS_ACCESS_KEY_SECRET=填写对应AccessKeySecret
MEDIX_SMS_SIGN_NAME=恒创联众
MEDIX_SMS_TEMPLATE_CODE=100001
```

安装 `requirements.txt` 中的依赖后，用 `python run_web.py` 启动。该入口自动加载 `.env.sms`；从其他入口启动时，需自己注入这几个环境变量。更改本地配置后需重启服务。没有凭据时短信接口返回不可用，账号密码登录仍可正常使用。

## 在界面中使用

1. 先用原有账号密码登录，在「账号设置 → 账号信息 → 绑定手机号」中验证账号密码和短信验证码。
2. 退出后打开登录弹窗，点击「手机号验证码登录」，输入已绑定手机号，收码后登录。
3. 短信登录始终进入原账号；不会自动创建、合并或迁移账号。未绑定手机号需要先注册并登录账号，再绑定。暂不支持更换或解绑手机号。

验证码 6 位、有效期 5 分钟；同一手机号至少间隔 60 秒发送，每 15 分钟限制发送、核验次数。单次挑战最多核验 5 次，成功后不可重复使用。登录和绑定使用不同的短信方案，绑定挑战另绑定当前用户。实际发短信会产生阿里云费用。

## 对其他模块的影响

仍使用原来的 Session Cookie、`require_user` 和 `user.id`，无需调整 profile、记忆、会话或知识库的隔离键。`/api/auth/me` 新增 `phone_masked`，不返回完整手机号。

## 官方文档

- [短信认证测试及赠送签名](https://help.aliyun.com/zh/pnvs/user-guide/sms-authentication-service)
- [发送验证码](https://help.aliyun.com/zh/pnvs/developer-reference/api-dypnsapi-2017-05-25-sendsmsverifycode)
- [核验验证码](https://help.aliyun.com/zh/pnvs/developer-reference/api-dypnsapi-2017-05-25-checksmsverifycode)

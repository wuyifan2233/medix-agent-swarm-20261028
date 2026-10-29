# 手机号账号使用说明

- 注册：手机号、短信验证码、密码及确认密码。注册成功后登录；不再通过验证码登录自动创建账号。
- 默认登录：手机号与密码；可切换手机号验证码登录。
- 忘记密码：验证已绑定手机号后重设密码，旧会话失效。
- 显示名默认使用 MediX 用户加手机尾号，仅供展示，不是登录账号。
- 数据仍按 user.id 隔离，修改密码不改变用户 ID 或资料、记忆归属。
- 本地凭据保存在被 Git 忽略的 .env.sms，配置 MEDIX_SMS_ACCESS_KEY_ID、MEDIX_SMS_ACCESS_KEY_SECRET、MEDIX_SMS_SIGN_NAME、MEDIX_SMS_TEMPLATE_CODE。使用 python run_web.py 启动，更改配置后重启。
- RAM 权限仅需 docs/ALIYUN-SMS-POLICY.json 中的发送、核验接口。
- 同一手机号发送间隔至少 60 秒，验证码 5 分钟有效，短信实际发送会产生费用。

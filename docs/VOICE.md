# MediX 语音输入与云端播报：实现方案

## 目标与选型

文字问答沿用现有 DeepSeek 配置、Agent 和工具流程。语音输入直接进入原有可编辑输入框，用户自行点击发送；回答保留文字、复制、朗读和停止入口。

截至 2026-10-31 查阅 [DeepSeek API 文档](https://api-docs.deepseek.com/)及其 [sitemap](https://api-docs.deepseek.com/sitemap.xml)，未发现公开的 TTS/audio-speech 接口。因此不能把 DeepSeek 文本模型名称或 Key 填到语音接口。OpenAI 有独立 TTS API，但本方案按需求不使用。

选用 [edge-tts](https://github.com/rany2/edge-tts) 7.3.1，从服务端调用 Microsoft Edge 在线朗读服务，不使用浏览器 speechSynthesis，不需要 API Key，也不把 DeepSeek Key 转给微软。它是第三方客户端，非 Azure 付费服务的正式 SLA 接口；当前无 Key 使用不代表永久免费或可保证生产可用性。若以后需要稳定配额，可替换 web/speech.py 适配器为有合同/配额的云端服务。

## 执行步骤与代码职责

1. requirements.integration.txt 固定 edge-tts 依赖，requirements.web.txt 委托到此统一入口，安装到服务实际使用的 medix-bootstrap 环境。
2. config.py 独立配置 TTS provider/voice/rate/pitch/volume，ASR 的 MEDIX_AUDIO_* 与文本配置保持原有凭据边界。
3. web/speech.py 适配 Edge 异步流，仅转发 audio 分片，不拼接完整音频，最多 16 MiB；单次总计最多 60 秒，连接 10 秒、接收 30 秒。音频为空、过大、依赖缺失、服务异常和超时均返回可处理错误，不记录播报正文或凭据。
4. POST /api/voice/speech 沿用原有接口，清理 Markdown；空内容或非法类型返回 400，清理后超过 4000 字返回 413；收到第一段音频后返回 audio/mpeg 流，设置 Cache-Control: no-store、X-Accel-Buffering: no，不发送 Content-Length。首段之前的错误返回对应 HTTP 状态，已开始的音频流若中断则关闭传输，不把 JSON 错误追加到 MP3。
5. GET /api/health 分开返回 speech_api_configured（ASR）与 tts_configured/tts_provider/tts_voice/tts_streaming（TTS）。配置可用不代表已探测云端网络。
6. 前端 POST /api/voice/speech/prepare 获取仅当前登录账户与会话可用的短期、一次性播放 URL，再以原生 Audio.src GET /api/voice/speech/stream/{token} 渐进播放 MP3；不调用 response.blob() 等待完整下载。准备地址不启动合成，文本不进入 URL；票据有效期 120 秒，最多 64 个，过期/重复使用返回 404，容量已满返回 429。显示“生成中 · 停止”“缓冲中 · 停止”和“停止”。停止时取消准备请求、暂停播放器、移除 src 并调用 load() 中止取流；服务端取消上游合成并关闭连接，过期响应不得开始播放。失败提示重试，保留文字，不回退系统朗读。
7. 更新测试、真实 HTTP 合成，保存测试流程/报告/固定示例音频到 E:/AIProject/medix-tts-tests。

## 默认声音和偏好

默认 zh-CN-XiaoxiaoNeural（中文女声），语速 -5%，音高与音量不额外改变。以自然停顿、略慢语速提供亲切感；“温柔”是主观听感，需要人工试听，不能保证每位用户感受一致。Edge 不支持任意情绪提示词，不能把“温柔”当作生成模型指令。

```powershell
$env:MEDIX_TTS_PROVIDER = 'edge'
$env:MEDIX_TTS_VOICE = 'zh-CN-XiaoxiaoNeural'
$env:MEDIX_TTS_RATE = '-5%'
$env:MEDIX_TTS_PITCH = '+0Hz'
$env:MEDIX_TTS_VOLUME = '+0%'
```

这些变量在启动服务之前设置；未启用账号回答偏好时使用服务配置的默认声音。实际可用列表可用 Python 模块 edge_tts --list-voices 查看。

### 个性化语音包（2026-10-31）

侧栏“个性化声音”或“回答偏好”打开同一个设置面板。默认选择“跟随沟通语气”，根据当前账号已保存且已启用的回答偏好选择声音，也可以固定选择语音包：

| 沟通语气 | 自动语音包 | Edge 音色 | 语速 |
| --- | --- | --- | --- |
| 温和鼓励 supportive | 温柔陪伴 gentle · 柔和女声，节奏稍慢 | zh-CN-XiaoxiaoNeural | -8% |
| 直接清楚 direct | 清晰利落 clear · 明亮男声，节奏自然 | zh-CN-YunxiNeural | +0% |
| 客观平和 neutral | 平和舒缓 steady · 平和女声，清晰舒缓 | zh-CN-XiaoyiNeural | -3% |

固定选择优先于沟通语气。只依据明确的表达偏好，不用年龄、疾病或健康档案推断声音。音色和语速由服务端白名单控制，前端不能提交任意供应商地址、voice ID 或凭据。

勾选“在后续问答中使用已保存的回答偏好”并保存后，下一次自动或手动播报使用新声音；文字偏好从下一次提问生效，已有回答不改写。关闭总偏好开关时仍使用服务默认声音（默认声音 -5%），不应用已保存的个性化语音包。自动朗读开关独立决定是否自动播放，不决定音色。

“试听当前声音”按当前未保存的语音包及语气播放固定短句，不调用 DeepSeek，不提交聊天内容，也不保存偏好。试听与回答共用一个播放器，可随时停止；关闭设置、修改选择或切换账号会停止试听，保存设置会停止当前播放。选择与保存操作沿用现有账号偏好、revision 冲突检查和同一业务数据库，无需迁移；旧偏好记录缺少 voice_profile 时按 auto 处理。

GET /api/voice/voices 返回当前账号可用语音包目录、语气映射、有效音色及偏好版本。POST /api/voice/speech/preview 接受 {"profile_id":"auto","tone":"supportive"}，只生成固定短句的一次性播放地址。目录需登录，试听请求沿用 Origin/CSRF 校验；试听地址同样绑定账号及登录会话。正式播报的 /speech 和 /speech/prepare 均从服务器读取账号偏好，不信任客户端指定音色。prepare 快照当次 TTS 配置，后续其他请求或偏好修改不会改变这张票据的声音。


## 播报时机与流程

完整回答完成后，按“回答自动朗读”偏好播报一次；集成版默认关闭，由当前账号明确开启后按账号在本浏览器保存；不继承其他账号的设置。恢复历史回答不触发自动朗读。手动朗读和停止始终保留。工具进度、检索轨迹、未完成 token 不播报。前端清理表格/来源等装饰，服务端再次清理 Markdown。浏览器阻止自动播放时提示用户点击朗读。

```text
麦克风 → 浏览器 SpeechRecognition（或已配置的 ASR）
       → 原有文字输入框 → 修改/补充 → 用户点击发送
       → 原有 DeepSeek / Agent 流程 → 完整文字回答
       → 自动/手动朗读 → prepare 获取临时地址 → Audio.src 请求流
       → Edge 微软云端合成 → MP3 分片实时转发 → Audio 边接收边播放
       → 停止/结束 → 释放资源
```

## 流式播放与延时

本次优化的是音频边生成边传输、边播放：首个 MP3 分片可用后立即发送，后续分片持续转发；不等待整段合成完成。完整文字回答仍通过原有流程生成，不播报未完成的医疗回答，也不新增 DeepSeek 改写请求。音色由当前账号已启用的偏好解析，关闭偏好时使用服务默认声音。

原生 Audio 使用浏览器的渐进式 MP3 解码与缓冲，无需依赖 MP3 MediaSource 支持。不提供 seek/Range 或音频缓存；回放会重新生成。网络延迟、云端首次响应以及浏览器起播缓冲仍会影响首声，不能承诺零延迟。代理部署还应关闭响应压缩/缓冲。实测分别记录 prepare、首段音频和完整接收耗时；首段到达不等于真实扬声器开始发声。

## 语音输入与数据处理

浏览器 SpeechRecognition 优先，无需服务端 Key，但不承诺离线，处理方式由浏览器供应商决定；跨浏览器录音可通过 MediaRecorder 和原有 /api/voice/transcribe 适配兼容 ASR。阿里 Paraformer、Whisper/faster-whisper 或其他专用 ASR 可经服务端适配返回 {text}，不改变 DeepSeek 文本调用。DeepSeek 文本 API 不自动成为 ASR 服务。

MediX 运行时不落盘用户录音和合成音频；TTS 正文会发送到微软云端处理。测试脚本只用固定非敏感样例，明确将样例 MP3 保存到测试目录用于试听。服务端日志只记录异常类型，不记录上游详情、正文或 Key。

## 验收

自动检查接口契约、ASR/TTS 解耦、Markdown 清理、非法输入、依赖缺失、上游失败、空音频、超限、超时、前端停止/过期响应、JS 语法和现有 web 单测。新增确定性分片提前到达、首段前/首段后断开清理与一次性票据测试；真实请求验证 3 个固定中文样例、MP3 帧及估算时长，另以长样例记录渐进下载时间与分块响应头；机器检测不能证明药名/数字发音正确或主观温柔度。

人工补充：在网页回答下朗读、停止、切换回答；检查自动朗读偏好；听取测试 MP3 中的中文、数字、单位和停顿；麦克风结束后修改文本再发送。人工项目不在报告中冒充自动通过。

可重复运行命令与实际报告：E:/AIProject/medix-tts-tests/README.md。

## main_copy 合并适配（2026-10-31）

语音接口统一使用 require_user，写请求沿用 Origin、X-Medix-Request 和 CSRF 验证，不创建匿名浏览器身份。前端使用 MedixAuth.fetch；原生 Audio GET 自动携带同源 HttpOnly 会话 Cookie，票据同时绑定 users.id 和登录 session id。其他账户、同一账户的新会话均不能使用旧票据；退出登录、切换账户或新对话时取消录音/播报，延迟回调也不得恢复播放。

云端 ASR 使用 JSON 请求以符合统一写接口规范：POST /api/voice/transcribe，body 为 {"audio":"录音的 Base64 字符串","content_type":"audio/webm;codecs=opus"}。服务端有界读取、校验 Base64 和解码后大小，随后沿用供应商 multipart audio/transcriptions 调用；返回 {"text":"识别结果"}。录音最多 16 MiB，JSON/Base64 传输增加约三分之一体积。浏览器原生听写流程不变。

合并回归：

```powershell
conda run -n medix-bootstrap python scripts/verify_integration.py
node --check web/static/app.js
node web/test_voice_playback.cjs
```

集成回归使用隔离的临时数据库、真实账户 Cookie/CSRF 和模拟的云端服务，不消耗 DeepSeek 或语音 API 配额。旧外部测试脚本中的匿名 HTTP 请求不适用于本次合并后的私有语音接口；真实服务试听应登录网页后操作。新增账户界面与 main_copy 保持一致，不导入测试账户到业务数据库。

集成版保留总体语义路由和账号菜单Token用量入口。自动朗读采用显式开启，历史恢复不自动重放；手动朗读与停止保留，正文会提交微软云端处理。

本集成机Python3.10补验：依赖edge-tts==7.3.1已安装，38项语音及网页边界测试通过，播放器12项测试及账号自动朗读同意隔离测试通过。固定非敏感短句云端音频18,144字节，26分片，首片1.3秒，总1.55秒。未自动授权麦克风、未上传真实病历测试朗读，不宣称识别准确度和人工听感已验收。

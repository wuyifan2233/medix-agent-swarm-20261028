# MediX 语音偏好与语音包配置方案

> 本文仅为实现方案，不包含代码或运行配置变更。方案以当前 MediX 的 Web Speech API 回退和 `/api/voice/speech` 服务端合成为基础。

## 目标

让用户选择自己偏好的播报声音，并调节语速等简单选项；偏好能在后续访问中保留。选择声音不应改变 DeepSeek 等文本模型、聊天提示词或医学回答流程。每条回答继续显示可读文字，并保留手动朗读和停止入口；录音识别结果进入可编辑输入框，仍由用户决定是否发送。

## 现有实现与边界

- 文本问答沿用 `config.py` 中的 `LLM_CONFIG` 和现有 Agent 调用链。DeepSeek 负责文字回答，不负责提供语音包。
- 语音配置在 `SPEECH_CONFIG` 中，目前只有一个服务端 `tts_voice`、模型、格式和播报指令。`/api/voice/speech` 接收文字，在服务器端请求兼容 OpenAI 音频格式的服务。
- 浏览器没有远端 TTS 配置时，前端使用 `speechSynthesis`，从操作系统和浏览器提供的 `SpeechSynthesisVoice` 列表中选择中文声音。不同电脑上可选项、名称和效果可能不同。
- 服务端 TTS 与浏览器本地声音是两种不同来源。用户在设置中应能看出声音来自“设备声音”还是“在线语音服务”，并能试听后再选择。
- DeepSeek 的 OpenAI 兼容文本接口不能据此推断它提供 TTS。不要把文本 Key 自动发送给另一个语音供应商；远程音频端点必须有独立、明确的服务器配置。

## 产品交互建议

在侧栏现有“回答自动朗读”开关下方增加“语音偏好”入口，打开轻量设置面板。首版包含：

1. **声音来源**：`设备语音`、`在线语音`。未配置在线服务时隐藏或禁用在线选项，并说明可以继续使用设备语音。
2. **声音卡片**：显示中文名称、性别/风格描述、语言、来源和试听按钮；例如“温柔女声 · 普通话 · 设备”。在线音色以服务端配置的可用声音为准。不要仅按 voice ID 推断性别或口音。
3. **试听**：朗读一段固定、无个人信息的短句，例如“你好，我是 MediX。我们一起把这件事慢慢说清楚。”试听使用同样的选中音色、语速和播报路径，不向模型提交聊天或病历内容。
4. **基础调节**：语速滑杆（建议 0.85–1.15，默认 0.96）；音高只对设备语音开放，在线 TTS 是否支持由供应商决定。首版不提供音量滑杆，使用系统媒体音量，减少跨设备的歧义。
5. **默认行为**：自动朗读开关独立保留；语音偏好只决定音色和速度。手动“朗读/停止”按钮始终显示。无论是否自动朗读，完整回答文字都保留在页面。
6. **明确反馈**：选择后显示“已使用设备声音”或“已使用在线语音”。在线请求失败时提示并回退设备声音；不得静默更换后仍显示在线音色。

设置面板在窄屏下改为底部抽屉，卡片有清楚的焦点态和屏幕阅读器标签。试听时同一时刻只允许一段声音播放；用户可随时停止。遵循 `prefers-reduced-motion`，不依靠动态波形作为唯一状态提示。

## “语音包”的两种来源

### 设备语音包

浏览器通过 `speechSynthesis.getVoices()` 枚举已安装并暴露给网页的声音；`voiceschanged` 事件用于异步刷新列表。前端用 `SpeechSynthesisUtterance.voice` 指定选择，并设置 `lang`、`rate`、`pitch`。如果列表为空或选中的设备声音后来不可用，回退至系统默认中文声音。

设备声音不是随 MediX 下载的模型文件。用户需要在操作系统或浏览器可用的语音设置中安装/启用相应普通话语音包；网页只能列出运行设备实际提供的声音。保存设备 voice URI 前应容忍 URI 在系统升级或另一台设备上变化：无法匹配时回退到默认，并提示用户重选。不要将完整设备声音清单同步到服务器。

### 在线语音包

由管理员在服务器端配置供应商、模型和允许使用的 voice ID，前端只获取供显示的安全目录，不拿到 API Key。第一阶段优先继续使用当前兼容 `/audio/speech` 的端点：每个服务端 voice profile 对应一个明确 `voice` 值及可选 `instructions`。如果目标供应商的接口不同（例如特定中文 TTS 服务），在服务端实现 adapter，把统一的 MediX 请求转换为供应商请求，并把结果转为音频响应；不在浏览器里放供应商 SDK 密钥。

音色 ID 通常不能跨模型或供应商互换。配置的 profile 必须绑定自己的 provider、model、voice ID 和格式。更换端点后，应重新验证 profile；无效 voice 应返回清楚错误并回退设备声音。

建议的服务端目录结构（示意，具体文件格式在实现前决定）：

```yaml
speech:
  default_profile: warm_zh
  profiles:
    warm_zh:
      label: 温柔女声
      locale: zh-CN
      style: 温和、自然、清晰
      provider: openai_compatible
      model: <服务端支持的 TTS 模型>
      voice: <该模型支持的 voice ID>
      format: mp3
      instructions: 请用自然、清晰、亲切的普通话播报，数字读准确，重点处稍作停顿。
    clear_zh:
      label: 清晰中性声
      locale: zh-CN
      style: 清晰、平稳
      provider: <已接入的服务端 adapter>
      model: <服务端模型>
      voice: <该模型支持的 voice ID>
      format: <adapter 支持的格式>
```

目录中仅放 voice ID、名称、语言、风格和模型等非秘密信息。API Key 继续从本机环境变量或被 Git 忽略的本地配置读取，例如 `MEDIX_AUDIO_API_KEY`；若不同 profile 使用不同供应商，建议采用按 provider 命名的独立密钥变量。不能将 Key 放进 profile JSON、静态页面、浏览器存储、返回给前端的健康接口或版本库。

## 推荐偏好数据

第一阶段仅保存在浏览器 `localStorage`，用带版本号的结构并对未知值安全回退：

```json
{
  "version": 1,
  "source": "device",
  "deviceVoiceURI": "<浏览器枚举到的 voiceURI>",
  "onlineProfileId": "warm_zh",
  "rate": 0.96,
  "pitch": 1.0,
  "autoSpeak": true
}
```

只保存用户偏好，不保存播报文本、录音、生成的音频或可用于认证的凭据。voiceURI 不保证跨设备一致；如果以后新增登录和跨设备偏好同步，应只同步在线 profile ID 和基础语速等偏好，不同步设备 voiceURI。

## 前后端接口演进

当前 `/api/voice/speech` 只接受 `{text}`，服务器使用默认 TTS 配置。实现偏好后，建议按以下方式演进：

- 新增只读 `GET /api/voice/voices`，返回可用 profile 的 `id`、显示名、语言、风格、来源和支持的调节项；绝不返回密钥、上游 URL 中的凭据或内部错误。
- 将合成请求扩展为 `{text, profile_id, rate}`。服务端只接受目录 allowlist 中的 `profile_id`，从服务器配置取得 provider、model 和 voice；客户端不能任意传 voice ID、上游 URL、API Key 或 instructions。
- 保持 `/api/voice/speech` 返回音频的约定，让现有播放器、停止控制和回答 UI 继续使用。若以后需要流式播报，再单独定义流式协议，不将普通音频响应误当作流式。
- 健康接口只返回“是否存在可用在线 TTS profile”及安全的能力标志。若在线 TTS 不可用，UI 可以列出设备语音并在设置中隐藏在线声音卡片。
- 远程请求设置超时、文字长度上限和音频响应大小限制；日志记录 profile ID、状态码类别和耗时，不记录用户播报原文或 Key。

初期不建议允许用户粘贴任意供应商 URL 或 voice ID。这会带来 SSRF、未经审查的目标地址和 provider 参数错误风险，也会让 UI 失去可预测性。要支持新供应商时，通过受控 adapter 和管理员配置新增 profile。

## 供应商接入优先级

1. **先完成设备声音选择**：无需新增密钥或后端依赖，可验证偏好面板、试听、语速、持久化和跨浏览器回退。测试覆盖 Windows 常见中文 voice 列表为空、异步加载、用户选择的 voiceURI 不再存在等情况。
2. **兼容端点的多 voice profile**：复用现有服务端 TTS 请求形式和 `MEDIX_AUDIO_*` 配置。上线前验证所选模型实际支持对应 voice 和中文输入；不要因名称像“中文”就假设服务商能自然地读好中文。
3. **中文质量优先的 provider adapter**：对候选服务使用独立 API Key，评估普通话音色、延迟、费用、稳定性、数据处理区域和保留策略。可以评估阿里云 Qwen TTS/CosyVoice、Azure Neural TTS、Google Cloud TTS 等，但应以部署时当前的模型名称、voice catalog、价格和服务条款为准，并试听实际医学文本后再决定默认音色。
4. **暂不把克隆音色作为首版选项**：声音克隆涉及授权、冒充风险和额外敏感数据管理；若将来支持，应单独做身份授权、删除机制和严格的服务端隔离。

医学播报评测样本应覆盖常见中文、药品名、检查项目、剂量、日期、百分比、单位和缩写。评价普通话自然度、温和程度、数字/单位准确度、停顿、首段延迟、完整播报耗时、失败率和单位成本。严禁只凭供应商的“自然音色”宣传确定默认选项。

## 分阶段实施

**阶段一：设备偏好**

- 枚举可用浏览器声音并提供手动选择、短句试听、语速/音高调节。
- 保存到本地浏览器；自动朗读开关与声音偏好分开。
- 远端音频服务未配置时仍能使用设备声音。

**阶段二：服务端 profile 目录**

- 为现有 TTS 增加服务端 allowlist 和 profile 目录接口。
- 增加在线音色试听与选择；服务端做 profile 校验、错误处理和安全日志。
- 在线请求失败时明确提示并回退设备声音。

**阶段三：中文语音供应商对比与接入**

- 使用固定的非个人测试语料评测多个中文 voice。
- 对选定供应商增加独立 adapter、密钥和运维说明；文字模型配置保持原样。
- 只有评测满足普通话质量、医学数字清晰度、延迟、成本及数据政策要求后，才把该音色设为推荐默认值。

## 验收标准

- 用户可以在不同来源之间切换、试听和保存偏好；刷新页面后偏好仍有效。
- 设备语音目录异步加载时 UI 有稳定状态，找不到已保存 voiceURI 会安全回退并允许重选。
- 在线 profile 必须来自服务端 allowlist；错误 profile 被拒绝，密钥不进入浏览器。
- 远端服务未配置或合成失败时，手动朗读仍能回退到设备语音；无法回退时给出清楚提示。
- 选中的语速应用于手动和自动播报；自动朗读可独立关闭；停止按钮可以中断当前音频。
- 回答文字始终可见、可选中和可复制；播报不改变回答、不自动提交聊天消息。
- 语音设置在窄屏可用、键盘可操作、屏幕阅读器能读出音色和播放状态。
- 语音偏好数据不含聊天正文、录音、生成音频或 API Key。

## 参考资料

- [MDN：SpeechSynthesis](https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesis)
- [MDN：SpeechSynthesis.getVoices](https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesis/getVoices)
- [MDN：SpeechSynthesisVoice](https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesisVoice)
- [OpenAI：Text-to-speech](https://developers.openai.com/api/docs/guides/text-to-speech)
- [阿里云：模型服务非实时语音合成](https://help.aliyun.com/zh/model-studio/non-realtime-tts-user-guide)
- [Azure：Text to speech](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/text-to-speech)
- [Google Cloud：Text-to-Speech](https://cloud.google.com/text-to-speech/docs)

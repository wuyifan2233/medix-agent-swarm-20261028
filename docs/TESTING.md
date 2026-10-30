## main_copy 2026-10-30 集成验收

`python scripts/verify_integration.py`：311 项通过，使用合成账号与模拟外部服务。本地 BGE/Milvus 实际初始化 180 条并检索返回3条。浏览器检查1366×768、390×844，登录与设置弹窗正常，控制台无错误。统一安装清单通过 pip 全新环境 dry-run 解析；未在全新电脑安装。实际短信、LLM/VLM、证据嵌入、Mem0、微信/QQ外部通信待独立配置联调。详细边界见 INTEGRATION.md。

以下为成员原分支的历史验证记录，不代表已在集成版复现真实服务调用。

## 2026-10-30 问答执行失败补充回归

`python -m unittest web.test_web web.test_provider_errors memory.test_case_memory -q`：25 项通过。
新增验证 LeadAgent / Worker 的鉴权错误不被吞掉、不重复循环请求，任务返回不可重试配置错误，
并隐藏原始提供商响应。真实浏览器使用临时模拟401实例确认显示配置字段且无“重新分析”按钮。
正式服务已重启加载修改。当前有效配置的真实最小模型请求仍返回401 invalid_api_key，
未再重复调用；成功生成回答需用户提供有效且匹配提供商的密钥。

## 2026-10-30 macOS 本机验收

- 项目 `.venv`（Python 3.10.7，复用本机已有包）运行 `python -m unittest web.test_web -v`：12 项通过。
- 真实浏览器：主页、侧栏、知识库弹窗、虚构图片示例预览与提交通过；单独无密钥测试进程可打开页面，提交后明确提示配置密钥。
- 知识库：180 条记录加载成功；独立临时数据库真实检索“高血压生活方式”返回 3 条，最高相似度约 0.785。
- 修复 Milvus 默认空闲心跳过密导致的断连，以及快速重启时端口预检查受 TIME_WAIT 影响的问题。
- 真实图文请求被现有模型密钥拒绝（401）；未完成成功回答、多轮模型问答及 Mem0 云端验证。未修改现有密钥，用户可填写 `config.py` 末尾的 `LOCAL_API_KEY` 后重启。
- 网页和 Milvus 均仅监听 127.0.0.1。后台进程可在当前登录期间继续运行，但未配置开机自启。

# 测试与验证说明

返回 [项目 README](../README.md)。在项目根目录执行以下命令。

## 验证范围

当前 Windows + Python 3.12 环境已完成过文字问答、图像读取、当前对话追问、多 Agent 协作、实际本地知识库检索及 Mem0 写入/跨客户端检索/清理验证。

2026-10-28 最近一次 UI 改版：`web.test_web` 的 7 项测试通过；真实浏览器中完成了虚构血压记录的图片读取、回答和来源展示，并检查了桌面及手机布局、知识库弹窗与推荐问题切换。UI 测试中出现的三个血压记录为 128/82、136/88、124/80 mmHg，对应脉搏为 72、76、70 次/分；仅作为图片读取的测试数据。

以上是已有环境的验证记录，不代表其他模型、操作系统、持续可用性或医学结论的验证。不要使用“全部功能 100% 通过”“保证诊断准确”等描述。模型训练、历史会话恢复、Redis 和独立 Qdrant 服务不属于本次已验证范围。

## 1. 网页边界与上下文回归

```powershell
..\.medix-venv\Scripts\python.exe -m unittest web.test_web -v
```

不需要真实模型或 Mem0 Key，不调用外部模型。覆盖：

- 图片重编码后仍保留像素尺寸。
- 拒绝伪装成图片的内容及 SVG。
- 拒绝空提问和非本地来源的 POST。
- 不允许其他浏览器读取当前浏览器任务。
- Swarm 子任务保留图片事实、原始问题与会话上下文。

这些测试不能替代真实浏览器的布局、文件选择和联网问答检查。

## 2. 不调用真实模型的核心检查

```powershell
..\.medix-venv\Scripts\python.exe verify_runtime.py offline
..\.medix-venv\Scripts\python.exe verify_runtime.py regression
```

`offline` 检查共享上下文、能力与身份、短期记忆、约束、输出修复和熵管理。`regression` 检查会话去重和编号式研究结果解析。

脚本会写入对应的 `verification_<模式>.json`。部分检查可能创建本地测试身份文件；它们不是训练或网页历史会话。

## 3. 实际知识库检索

先停止占用同一数据库的网页或命令行实例，确保嵌入模型已缓存或可下载，再运行。默认医学集合为空时会自动导入，无需手动迁移：

```powershell
..\.medix-venv\Scripts\python.exe verify_runtime.py kb
```

验证实际命中、类型过滤、相似度范围及当前附带数据的 180 条记录。该数量断言针对项目提供的数据；自定义索引后需同步调整测试预期，不能把测试脚本当成通用健康检查。

知识库自动初始化回归：`python -m unittest knowledge.test_bootstrap`。覆盖新目录自动导入、已有空集合恢复、重复启动、保留自定义数据、源文件只读、旧库路径误配置、维度不符和自定义嵌入模型。此组使用模拟Milvus客户端，不启动数据库服务、不调用模型API；真实检索仍使用上面的 `verify_runtime.py kb`。

## 4. 真实 API、工具和搜索研究

```powershell
..\.medix-venv\Scripts\python.exe verify_runtime.py api
..\.medix-venv\Scripts\python.exe verify_runtime.py skills
..\.medix-venv\Scripts\python.exe verify_runtime.py research
```

需要通过当前进程环境或外部配置提供可用密钥。会发起真实模型调用并消耗额度；研究模式还可能联网搜索。不要把真实个人健康资料作为测试输入。

`api` 覆盖 Agent Loop、工具调用、简单路由和复杂任务；`skills` 检查指定技能的实际资料检索；`research` 检查搜索与本地资料综合。知识库相关模式也需要独占当前 Milvus Lite 数据目录。

## 5. Mem0 独立验证

在已通过安全方式向当前进程提供 `MEM0_API_KEY` 的环境中运行：

```powershell
..\.medix-venv\Scripts\python.exe verify_mem0.py
```

脚本使用带随机 UUID 的独立测试用户，写入“喜欢蓝色”的虚构偏好，以新客户端检索，然后删除这个测试用户下本次生成的记忆并检查剩余数量。不会主动读取或清理网页真实用户的摘要。

这会真实调用 Mem0，并写入 `verification_mem0.json`；检查最终状态和清理结果。网络或清理失败时不应只凭写入成功就报告整体验证通过。

## 6. 综合套件的边界

```powershell
..\.medix-venv\Scripts\python.exe verify_runtime.py full
```

该模式会运行 `examples/test_all.py` 中列出的测试，但**明确跳过 `test_long_term_memory`**，跳过原因文本也固定为未提供 Mem0 Key。即使环境里有 Key，也不能把该模式宣称为 Mem0 实测通过；请单独运行 `verify_mem0.py`。

直接执行 `python examples/test_all.py` 是另一条旧入口，其行为与包装脚本的跳过策略不同。综合套件可能调用真实外部服务并创建本地会话总结，运行前需了解数据和费用范围。

## 7. 真实网页检查建议

1. 启动网页，等待知识库状态就绪。
2. 发送一个普通问题，确认真实回答与检索参考。
3. 点击“试用图片示例”，检查预览、移除、再次添加和发送。
4. 确认三次记录读取正确，再不附新图追问第二次记录。
5. 新建对话，确认旧图片上下文不沿用。
6. 用复杂虚构任务检查实际参与的 Agent 数量，不预先假定所有任务必然触发多助手。
7. 检查窄屏菜单、输入区、弹窗、推荐问题切换、错误提示和重试。
8. 如验证 Mem0，在确认独立密钥配置后手动开启，再区分摘要记忆和完整聊天历史。

## 验证文件与日志

根目录中的 `verification_*.json`、`*-smoke.log` 及 UI 截图是历次检查产物，不是启动必需资源；不能仅凭文件存在就断言当前接口仍可用。

`web-network.*.log`、`web-restart.*.log` 等文件来自特定的后台启动方式，`start_web.ps1` 本身不会固定创建这些日志。命令行入口可能保存会话总结；网页服务配置为不记录问题正文。分享项目或排障输出前，应先检查已有日志和测试产物是否包含对话内容，避免将其当作空白模板发布。

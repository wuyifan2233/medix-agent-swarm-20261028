# main_copy 集成入口（优先阅读）

启动与团队验收先阅读 docs/TEAM-VALIDATION.md，代码接入阅读 docs/INTEGRATION.md 与 docs/AUTH-INTEGRATION.md。统一安装 requirements.integration.txt，启动 run_web.py；本机验证 Python3.10。业务数据库只有一份，Alembic 单一 head 20261031_17，公共向量索引和云端 Mem0 用途独立。禁止重新引入匿名浏览器身份或独立业务 SQLite。请勿直接运行旧版 main.py 的未隔离记忆逻辑作为网页入口。集成回归执行 python scripts/verify_integration.py。以下原模块交付说明作为历史/模块背景，和本节冲突时以本节及当前代码为准。

# MediX 项目协作指南

## 本分支的证据库交付
- 最新完整设计与演示步骤先读 `knowledge/DESIGN.md`。当前3,298篇独立中文原文，默认本地BGE（512维），旧Qwen索引保留；`import_open_datasets.py`导入独立问法/评测素材，不把CMB答案或社区回答混入主证据。纯文字默认`MEDIX_EVIDENCE_GENERATOR=direct`单次生成，quote仅证明原文存在。新测试`knowledge.test_answering`。本机现已显式选择local；Gitee与硅基流动作为可选远程后端保留。
- 证据版默认嵌入后端为本地 `BAAI/bge-small-zh-v1.5`；可选 Gitee `Qwen3-Embedding-8B`，通过 `GITEE_AI_API_KEY` 配置；`MEDIX_EMBEDDING_PROVIDER=local` 可显式使用 BGE。`MEDIX_EMBEDDING_PROVIDER=siliconflow` 支持硅基流动 `Qwen/Qwen3-Embedding-8B`，使用 `SILICONFLOW_API_KEY`；所有后端必须使用独立版本索引，不允许自动回退或迁入旧向量。真实 Gitee 验证需有 Key；`knowledge.test_embeddings` 使用模拟 HTTP。
- `.env.local` 保存本机默认 `GITEE_AI_API_KEY` 和 `SILICONFLOW_API_KEY`，环境变量优先；该文件不得提交或展示。`MEDIX_RERANK_PROVIDER=none` 默认关闭可选硅基流动 Qwen 重排；填 Key 后显式设为 `siliconflow`，此开关不选择 embedding 后端；嵌入与重排开关均支持 `.env.local`。
- 先读 `docs/KNOWLEDGE_DELIVERY.md`。本分支基于同事 `feature/rag`，保留默认集合的空库自动初始化。
- 新克隆安装 `requirements.kb.txt` 后可直接用 `run_kb_demo.py` 启动（8766），缺失语料自动逐篇缓存获取，至少3000篇才发布；首次仍需联网获取正文和固定BGE模型。`--prepare-only`可提前构建。默认数据库在项目内`knowledge/data/evidence/`，普通 `run_web.py` 保持旧库兼容。
- `MEDIX_KB_MODE=evidence` 为显式开关；`MEDIX_EVIDENCE_ROOT` 与原 `MEDIX_DB_PATH` 分离。不要对证据库运行旧版迁移或样例导入。
- 来源全文、快照和构建状态位于忽略提交的 `knowledge/.local/`。未知再分发许可的正文不能加入交付包或 Git。
- 新验证：`python -m unittest knowledge.test_embeddings knowledge.test_reranking knowledge.test_bootstrap knowledge.test_evidence knowledge.test_query_policy web.test_web -v`；关闭占用同一证据版本的服务后运行 `python knowledge/scripts/evaluate_evidence.py`。真实生成未配置 Key 时不得宣称验证通过。

## 项目定位
- 本项目是本地健康问答 demo，支持文本、图片、RAG 和按需多 Agent 协作；没有训练或微调流程。
- 先阅读 `README.md`、`docs/RUNTIME.md`、`docs/TESTING.md`。以当前代码为准，不把规划中的模型、语音或历史会话功能描述为已实现。

## 代码地图
- `run_web.py` / `web/app.py`：FastAPI + Uvicorn 网页入口、图片校验、任务队列、浏览器隔离和会话上下文；前端位于 `web/static/`。
- `main.py` / `demo_basic.py`：命令行入口和示例。
- `core/`：LLM 客户端、ReAct 循环及技能加载注册。
- `agents/`、`swarm/`：专业 Worker、LeadAgent、路由、任务分解和共享上下文。
- `.claude/skills/`：运行时业务技能，不是开发协作指南。
- `knowledge/`、`research/`：Milvus 本地检索、联网搜索及证据综合。
- `memory/`：短期上下文、摘要、身份及可选 Mem0；`constraints/` 和 `validation/` 负责约束及输出修复。
- `config.py`：环境变量或外部配置读取；`runtime_paths.py`：数据库路径。

## 环境与启动
- 使用 Python 3.12；本机 conda 环境名为 `medix`。
- 创建：`conda create -n medix python=3.12 pip -y`。
- 安装：`conda run -n medix python -m pip install -r requirements.web.txt`。该清单引用完整版本快照；如版本不可用，应记录实际错误及兼容方案，不能声称原快照安装成功。
- 在项目根目录启动：`conda run --no-capture-output -n medix python run_web.py`。
- 本机快捷启动：`./start_conda.ps1`，默认把模型缓存放在项目内 `.medix-model-cache`；提前设置 `HF_HOME` 可覆盖。
- 网页地址：`http://127.0.0.1:8765/`；健康检查：`GET /api/health`。等待 `knowledge=ready`，附带资料预期为 180 条。
- 网页 warmup 自动迁移旧向量库。原有 `start.ps1` / `start_web.ps1` 固定引用项目上一级 `.medix-venv`，不能直接用于 conda 环境。
- `HF_HOME` 可指定模型缓存；默认项目上一级 `.medix-model-cache`。首次启动需要下载 `BAAI/bge-small-zh-v1.5` 或存在可读缓存。

## 配置与数据边界
- DeepSeek 通过 `.env.local` 的 `MEDIX_LLM_PROVIDER=deepseek`、`DEEPSEEK_API_KEY` 配置，默认 `deepseek-flash`、thinking enabled、reasoning_effort high；占位 `xxx` 不算已配置。同名进程环境变量优先；`auto` 保留旧模型配置优先级。共享读取位于 `runtime_settings.py`。工具调用的 `reasoning_content` 仅在内存中传回 API，不写入会话摘要或显示为回答。离线契约：`python -m unittest core.test_deepseek -v`。
- 通过进程环境提供 `OPENAI_API_KEY`、可选 `OPENAI_BASE_URL` 和 `OPENAI_MODEL`；也支持 `ARK_API_KEY` 或 `MEDIX_CONFIG_PATH` 指向的外部配置。不要输出、提交或在文档里记录真实密钥。
- Mem0 默认可选，使用独立 `MEM0_API_KEY`；不要为启动网页额外部署 Redis/Qdrant。
- 保留 `knowledge/data/documents/` 与旧库 `knowledge/data/milvus_lite.db`。迁移脚本只读旧库，不要反复运行原始导入脚本或删除数据库来解决锁冲突。
- 当前向量库默认位于系统临时目录的项目路径哈希目录；`MEDIX_DB_PATH` 可改为 ASCII 路径。同一数据库只能由一个运行实例占用。
- 不落盘上传图片；网页没有完整历史聊天恢复。保持 Cookie/任务归属检查、来源校验、图片大小限制和本地监听。
- 医学回答及随附资料未构成医学准确性认证；验证使用虚构数据。

## 修改与验证
- 修改知识库数据、存储、分块、检索、生成prompt或引用交互时，必须在同一提交同步 `knowledge/DESIGN.md`，保留历史验证报告；文档描述当前真实行为和默认配置。
- 保持现有 Python 模块结构和原生 HTML/CSS/JavaScript，避免无关重构。
- 基础检查：`conda run -n medix python -m unittest web.test_web -v`。
- 核心离线检查：`conda run -n medix python verify_runtime.py offline` 和 `conda run -n medix python verify_runtime.py regression`。
- `verify_runtime.py kb` 需要独占数据库及嵌入模型；停止网页后运行。
- `api`、`skills`、`research` 模式和 `verify_mem0.py` 会调用外部服务。报告中区分离线测试、知识库就绪和实际 API 验证；健康接口的 `model_configured` 不代表鉴权成功。
- 不提交日志、模型缓存、环境目录、会话摘要或 verification 产物。文档修改无需添加机械式测试。

- 扩库验收以独立原文计数，不以chunk凑数。来源分层和94病种/159药物名称覆盖清单见knowledge/DESIGN.md与coverage_inventory.json。不得把专业平台条目称为政府数据库或具体制剂核准说明书。新回归包含knowledge.test_bulk。

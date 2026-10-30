# 本地医学证据库交付与合入说明

## 范围与当前数据

这是常见病与基础用药科普演示，不是完整临床知识库或药品说明书系统。12 份来源，当前 Gitee Qwen 版为 56 个独立片段，原 BGE 版为 71 个；覆盖感冒咳嗽、流感、儿童鼻炎、胃肠炎、高血压、糖尿病运动管理，以及对乙酰氨基酚、布洛芬、氯雷他定、口服补液盐的基础知识。部分资料为儿童或老年人主题，回答应尊重原文适用范围。

原定部分政府网站返回 403/412/445，故改用可下载的专业机构来源：11 份来自中华医学会科学普及部，1 份为新疆大学药学院转载科普中国的布洛芬资料。不是国家药监局核准说明书，没有将科普包装成临床指南。页面保留发布机构、日期与链接；布洛芬转载页未核定发布日期，显示“日期未注明”。

`knowledge/sources.json` 是版本控制中的来源清单。`knowledge/.local/` 保存正文 Markdown、HTML 快照、哈希、获取日期及使用条件，已忽略提交。全文的再分发许可未确认，不能把本地快照直接加入 GitHub 或交付包；其他成员按脚本获取。来源核对仅表示 URL、机构与正文对应，不代表临床审核。旧版 TXT/SQLite 保持不变。

## 安装、构建与运行

### Gitee Qwen3-Embedding-8B（证据版默认后端）

嵌入接口为 `POST https://ai.gitee.com/v1/embeddings`，使用独立的 `GITEE_AI_API_KEY`，不要复用或覆盖聊天模型的 `OPENAI_API_KEY`。请求使用 `model=Qwen3-Embedding-8B`、`encoding_format=float`、显式 `dimensions=4096`，并严格校验响应。2026-10-29 实测省略 dimensions 时 Gitee 返回 1024 维，因此不能依赖原生模型维度推断服务端默认值。配置模板见根目录 `.env.example`；可复制成被 Git 忽略的 `.env.local` 保存本机默认凭据。嵌入及重排配置支持从 `.env.local` 读取，进程环境变量优先；模型缓存等其余运行配置继续使用环境变量。

在本机 PowerShell 通过隐藏输入设置凭据，再执行下方构建和运行命令：

```powershell
$secret = Read-Host 'Gitee AI API Key' -AsSecureString
$env:GITEE_AI_API_KEY = [System.Net.NetworkCredential]::new('', $secret).Password
$secret = $null
$env:MEDIX_EMBEDDING_PROVIDER = 'gitee'
```

默认每批 8 段，使用 30 秒请求超时及 SDK 的两次重试；`MEDIX_EMBEDDING_BATCH_SIZE` 可调整为 1–1000。Qwen 只下载 tokenizer 用于分块，不下载 8B 权重；可用 `MEDIX_EMBEDDING_TOKENIZER_PATH` 指向提前下载的 tokenizer。查询按 Qwen 官方建议添加 `Instruct: ...\nQuery: ...`，文档不加查询指令。向量按响应 `index` 重排，检查条数、4096 维、有限值及非零范数，然后 L2 归一化。

新索引版本包含后端、模型、维度、归一化方式、tokenizer revision 和查询指令，必须重建，不能复用旧的 512 维 BGE 向量。关键词召回使用已入库向量计算相似度，不重复向 API 发送文档。API 失败或缺 Key 时明确报错，不自动回退到 BGE，以免混用向量。

**数据流变化：选择 Gitee 后，入库的公开资料片段和实际检索问题会发往 Gitee AI；本地仍保存语料与索引。远程向量检索需要联网。** 不要向 demo 输入真实个人健康资料。`HF_HUB_OFFLINE=1` 只影响本地 tokenizer 下载，不会使 Gitee API 离线运行。

需要保留本地离线演示时，显式设置 `$env:MEDIX_EMBEDDING_PROVIDER='local'`，仍使用 BGE 和独立模型索引。普通旧库入口的模型与同事迁移逻辑不受影响。本节为新增接入；下文 2026-10-29 的 20/20 命中率、71 片段和延迟是此前 BGE 的验证记录，不是 Qwen 的效果结论。Qwen 重建后的 chunk 数与相似度分布可能变化，0.4 阈值需使用同一固定测试集重新核验。

官方参考：[Gitee 嵌入接口](https://ai.gitee.com/docs/openapi/v1#tag/特征抽取/post/embeddings)、[官方 OpenAPI YAML](https://ai.gitee.com/v1/yaml)、[Gitee 向量化示例](https://ai.gitee.com/docs/products/apis/embeddings/)、[Qwen 模型与查询指令](https://github.com/QwenLM/Qwen3-Embedding)。

2026-10-29 已使用本机默认配置完成真实 Gitee 构建与 30 题检索：56 个独立 chunk，4096 维，库内命中 20/20，库外和信息不足各 5/5，预热检索 p95 为 931.2 ms。记录见 `docs/qwen-evaluation.json`；没有调用聊天生成模型，也没有启用硅基流动重排。相同语料重启复用既有索引，不再次编码全部文档。

在本分支根目录执行，使用 Python 3.12：

```powershell
conda activate medix
python -m pip install -r requirements.kb.txt
python knowledge/scripts/fetch_sources.py
python knowledge/scripts/build_evidence.py
python knowledge/scripts/evaluate_evidence.py
python run_kb_demo.py --port 8766
```

打开 http://127.0.0.1:8766/，点击“医学知识库”，输入问题检索原文。无需聊天模型 Key 即可检索和查看证据，但默认 Gitee 后端需要嵌入 Key；聊天会明确返回“本地原文检索结果，未调用模型生成回答”。图像理解、Agent 综合回答仍需聊天模型 API 配置。

模型由 `HF_HOME` 决定缓存位置，首次下载后可设置 `HF_HUB_OFFLINE=1`；不要在模型未缓存时开启离线模式。若复用旧工作区缓存，先将 `HF_HOME` 指向该目录。

证据索引默认位于系统临时目录的 `medix-evidence/<版本>/milvus.db`，可通过 `MEDIX_EVIDENCE_ROOT` 指定独立的 ASCII 持久化根目录。根目录下由语料、分块版本和模型 revision 生成版本子目录。同一版本不能被多个进程同时打开。构建、评测需先停止占用该证据库的服务；单个服务的请求由工作线程串行执行。

再次构建相同来源不会重复插入。构建验证 chunk ID 和条目数；不完整索引会失败并要求选择新的根目录，不删除或覆盖旧数据。更新来源后先构建、评测，通过后再重启证据入口。回滚使用旧语料/代码版本及旧索引目录；不要手工覆盖正在使用的索引。

## 2026-10-30 优化交付

### DeepSeek 聊天生成配置

根目录 `.env.local` 可保存本机聊天模型配置，文件已忽略提交。填入 `DEEPSEEK_API_KEY` 后重启服务：

```dotenv
MEDIX_LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=xxx
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_THINKING=enabled
DEEPSEEK_REASONING_EFFORT=high
DEEPSEEK_MAX_TOKENS=8192
```

使用 `https://api.deepseek.com` 的 OpenAI 兼容接口，非流式调用；普通聊天和工具调用都带 `reasoning_effort` 与 `extra_body.thinking`。工具循环在内存中保留并传回 `reasoning_content`，不将其作为回答展示或写入会话摘要。参考 [DeepSeek 思考模式及工具调用要求](https://api-docs.deepseek.com/guides/thinking_mode/)。

进程环境中的同名配置优先于本机文件。`MEDIX_LLM_PROVIDER=deepseek` 显式选择 DeepSeek；`auto` 恢复既有 OpenAI/ARK/外部配置优先的行为，只有无既有 Key 且 DeepSeek Key 有效时才自动选择 DeepSeek。`xxx` 和空值视为未配置，网页继续返回检索原文；健康接口的 configured 只检查配置存在，不验证鉴权。聊天与嵌入/重排的配置独立，Gitee 和硅基流动 Key 不受影响。

新增离线验证：`python -m unittest core.test_deepseek -v`，覆盖本机 Key、环境覆盖、占位值、旧配置优先级和连续工具请求的 HTTP 契约。未填真实 Key，未验证真实 DeepSeek 生成和图像输入能力。

### 检索优化

- `MEDIX_EMBEDDING_PROVIDER=gitee|siliconflow|local` 可在 `.env.local` 中选择。硅基流动使用 `SILICONFLOW_API_KEY`、`https://api.siliconflow.cn/v1/embeddings` 和 `Qwen/Qwen3-Embedding-8B`，显式 4096 维；请求契约已用模拟 HTTP 验证，尚未真实调用。官方文档：[Embedding 接口](https://api-docs.siliconflow.cn/docs/api/embeddings-post)。更换后端必须先停止服务、构建并评测，后端/endpoint/model 都进入版本身份，即使同维度也不能混用向量。`MEDIX_RERANK_PROVIDER` 独立选择是否重排。
- 食物问题不再仅因“能吃吗”进入用药信息不足分支；增加血压高/血糖高等检索别名。短追问从最近用户消息继承主题，明确的新主题不继承；这是有限规则，不是通用意图模型。
- `knowledge/applicability.json` 标注当前 12 份资料的人群和科普属性。明确不匹配的人群被过滤，未明确人群的查询会展示需要核对范围；标签不是临床审核。
- 缺少说明书、缺少水果专题时显示资料缺口；回答生成提示也包含该缺口。逐句引用面板区分原文逐字匹配、引用待核对与未引用，不用编号有效性宣称语义支持。
- 下载改为完整暂存并校验后，原子切换来源清单；失败不会覆盖在用正文。保留旧布局读取能力及历史 generation，运行数据仍不提交。

本次 51 项测试通过；真实 Gitee 39 个检索用例全部通过，其中库内 25/25、库外 5/5、信息不足 6/6，另有资料缺口和人群不匹配检查。版本 `b2a633d17120f15b`，12 份资料、56 个 chunk，本次预热检索 p95 为 4039.9 ms，超过 2000 ms 延迟门槛，因此性能门槛未通过；详见 `docs/optimization-evaluation.json`。远程请求延迟波动明显，另一次运行 p95 达到 9475.6 ms，不能保证路演实时响应。这是固定小测试集的检索验证，尚未验证真实聊天生成、硅基流动嵌入或重排效果。

后续权威数据源及接入顺序见 [数据源扩展调研](KNOWLEDGE_SOURCES_ROADMAP.md)。新增来源尚未入库。

## 与同事 feature/rag 的兼容

本功能分支基于 `origin/feature/rag` 的 `9902806`，复用了同事的路径验证逻辑，保留自动入库修复。已实测独立空库首次初始化导入 180 行，再次初始化仍为 180 行，检索有结果；其 11 项测试通过。

两种入口明确区分：

- `python run_web.py`：保持原有默认知识库，使用 `MEDIX_DB_PATH` 和同事的默认集合自动初始化。
- `python run_kb_demo.py`：设置 `MEDIX_KB_MODE=evidence`，使用独立来源证据库及 `MEDIX_EVIDENCE_ROOT`，不会把旧版 180 行样例迁入证据集合。

同事提供的手工修复命令仍有效：`python knowledge/scripts/migrate_legacy_db.py`。迁移和普通项目启动必须使用相同 `MEDIX_DB_PATH`；目标必须是独立 V3 目录，不能指向 `knowledge/data/milvus_lite.db`。证据库不依赖这条迁移命令。

普通 `MedicalKnowledgeBase()` 无参数调用在显式 evidence 模式下返回证据实现，现有技能与研究工作流沿用 `search()` 接口；显式传入自定义数据库参数时仍保留原类行为。新资料主要是科普，`clinical_guideline`、`disease_classification` 类型可能没有结果，不用旧的未核实样例补齐。

建议先将同事 `feature/rag` 合入 main，再合入本分支自己的功能提交。新增核心代码集中于 `knowledge/`，共享改动仅为工厂入口、网页 API/UI 和研究来源格式。未修改配置密钥、Agent 路由、共享上下文或原始数据库；不包含“改造前后对比”。

## 检索与接口

### 可选硅基流动重排（不是 embedding）

`Qwen/Qwen3-Reranker-8B` 通过 `POST https://api.siliconflow.cn/v1/rerank` 对已召回的证据排序，不产生向量。填入 `.env.local` 中 `SILICONFLOW_API_KEY=xxx` 的占位值后，设置 `$env:MEDIX_RERANK_PROVIDER='siliconflow'` 并重启；默认 `none`，不发送重排请求。Key 的环境变量优先级与 Gitee 一致，两个凭据独立，均不提交 Git。

顺序为：向量与 BM25 召回 → RRF → 相关性/主题过滤及去重 → 前 10 段候选重排 → 最多 3 段证据。请求含 `model`、`query`、`documents`、`instruction`、`top_n` 和 `return_documents=false`；不发送文档规定不适用于该模型的 `max_chunks_per_doc/overlap_tokens` 参数。按响应 `index` 映射回原文，校验完整索引和有限分数，绝不采用服务端回传文本替换本地证据。

开启重排不改变 embedding 或索引版本，无需重新向量化。响应分数仅用于排序，不是医学可信度；接口超时、鉴权或响应错误时保留 RRF 顺序，并在检索过程展示降级状态，不伪报重排成功。开启后会将问题与最多 10 段候选原文发送至硅基流动。占位 Key 不能调用接口，真实服务效果需填 Key 后另行评测。官方文档：[重排接口](https://api-docs.siliconflow.cn/docs/api/rerank-post)。

按标题/段落切分，用当前嵌入后端的 tokenizer 限制含标题块最长 384 tokens，长段落按句子边界拆分并最多重叠 48 tokens；保存 Markdown 原文字符区间。中文分词使用 jieba，关键词检索使用 rank-bm25。语义和关键词各召回最多 10 个候选，按 RRF 融合，余弦相似度至少 0.4，内容去重，默认返回 3 段。

这是小型显式覆盖库：按来源主题和少量医疗术语做范围检查，库外问题不因偶然的向量相似度而返回证据。此规则会保守拒绝未覆盖的同义表达，不承诺通用医疗分类。具体用药、剂量、停换药与联合用药问题走保守提示规则，不进行个人剂量计算。

- `retrieve(query, top_k=3, filter_type=None)`：返回 `status`（`ok/no_results/needs_information/error`）、`hits`、`message`、`trace`。
- `search()`：兼容旧技能；错误抛出异常，无结果返回空列表。
- `GET /api/knowledge/catalog`：来源清单、版本和片段数。
- `GET /api/knowledge/retrieve?q=...`：无需聊天 Key 的检索，远程嵌入后端仍需要对应 Key；包含来源和检索过程，查询仅接受 1–8000 字；不落盘查询。仅在 evidence 模式就绪后可用。
- `GET /api/health`：增加 `mode=evidence`、`source_documents` 和 `version`。
- 聊天结果增加 `retrieval`、`retrieval_status`、`generation`、`invalid_citations`，来源包含完整证据、机构、日期、原始 URL、原文位置和哈希。

证据提供给模型时使用完整片段与编号，模型不得把资料内指令作为指令执行。无效编号会被替换并返回记录；编号合法不等于结论有依据，仍需人工核对答案。检索分数和融合分数均不是医学可信度。风险与症状技能仍有其既有规则判断，不应把它们描述为经知识库临床认证。

## 验证与路演

```powershell
python -m unittest knowledge.test_embeddings knowledge.test_reranking knowledge.test_bootstrap knowledge.test_evidence knowledge.test_query_policy web.test_web -v
python knowledge/scripts/evaluate_evidence.py
```

评测集为 `knowledge/evaluation_cases.json`：现为 39 题，25 个库内问题、5 个库外问题、6 个用药信息不足问题，另有 1 个人群不匹配和 2 个资料缺口问题。命中要求 top-3 中存在预期来源，且片段包含预先标注的证据词；不是答案准确率，也不是独立医疗基准。脚本同时验证全部 chunk 的 token 预算、原文位置、唯一 ID 和索引条目数。结果写入忽略提交的 `verification_evidence.json`，交付记录保存在 `docs/evidence-evaluation.json`。本机已配置 Gitee 嵌入 Key，但未配置聊天模型 Key，真实生成回答质量未验证。

2026-10-29 本机交付验证：27 项回归测试通过；库内 Hit@3 为 20/20，库外与信息不足各 5/5，预热检索 p95 为 180.3 ms。重复构建条目数仍为 71；网页实际完成无 Key 聊天原文返回、引用点击、来源展开、高亮及 390px 窄屏无横向溢出检查。延迟为本机固定语料结果，不是通用性能承诺。信息不足项验证的是规则提示，不是模型回答质量。

三分钟路演顺序：

1. 打开知识库，输入“家庭测量血压选择什么血压计”，展开检索过程，点击片段，核对机构、日期和原文位置。
2. 输入“口服补液盐配制时有哪些常见错误”，点击证据，展示关键词高亮和官方原始发布链接。
3. 输入“三岁孩子发烧布洛芬吃多少毫升”，展示知识库不从泛化科普计算个人剂量；再输入库外问题，展示资料不足。

若已配置图文与工具调用模型，可改在聊天区展示带编号的真实生成回答；无聊天 Key 时只展示原文检索，不能将其宣称为模型问答成功。路演前预热并检查 `knowledge=ready`。仅本地 BGE 模式可断网检索；已返回的证据可在页面展开，Gitee 查询编码、外部原文链接和模型生成需要联网。

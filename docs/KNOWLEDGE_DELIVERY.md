# 本地医学证据库交付与合入说明

## 范围与当前数据

这是常见病与基础用药科普演示，不是完整临床知识库或药品说明书系统。12 份来源、71 个独立片段；覆盖感冒咳嗽、流感、儿童鼻炎、胃肠炎、高血压、糖尿病运动管理，以及对乙酰氨基酚、布洛芬、氯雷他定、口服补液盐的基础知识。部分资料为儿童或老年人主题，回答应尊重原文适用范围。

原定部分政府网站返回 403/412/445，故改用可下载的专业机构来源：11 份来自中华医学会科学普及部，1 份为新疆大学药学院转载科普中国的布洛芬资料。不是国家药监局核准说明书，没有将科普包装成临床指南。页面保留发布机构、日期与链接；布洛芬转载页未核定发布日期，显示“日期未注明”。

`knowledge/sources.json` 是版本控制中的来源清单。`knowledge/.local/` 保存正文 Markdown、HTML 快照、哈希、获取日期及使用条件，已忽略提交。全文的再分发许可未确认，不能把本地快照直接加入 GitHub 或交付包；其他成员按脚本获取。来源核对仅表示 URL、机构与正文对应，不代表临床审核。旧版 TXT/SQLite 保持不变。

## 安装、构建与运行

在本分支根目录执行，使用 Python 3.12：

```powershell
conda activate medix
python -m pip install -r requirements.kb.txt
python knowledge/scripts/fetch_sources.py
python knowledge/scripts/build_evidence.py
python knowledge/scripts/evaluate_evidence.py
python run_kb_demo.py --port 8766
```

打开 http://127.0.0.1:8766/，点击“医学知识库”，输入问题检索原文。无需模型 Key 即可检索和查看证据；聊天也会明确返回“本地原文检索结果，未调用模型生成回答”。图像理解、Agent 综合回答仍需模型 API 配置。

模型由 `HF_HOME` 决定缓存位置，首次下载后可设置 `HF_HUB_OFFLINE=1`；不要在模型未缓存时开启离线模式。若复用旧工作区缓存，先将 `HF_HOME` 指向该目录。

证据索引默认位于系统临时目录的 `medix-evidence/<版本>/milvus.db`，可通过 `MEDIX_EVIDENCE_ROOT` 指定独立的 ASCII 持久化根目录。根目录下由语料、分块版本和模型 revision 生成版本子目录。同一版本不能被多个进程同时打开。构建、评测需先停止占用该证据库的服务；单个服务的请求由工作线程串行执行。

再次构建相同来源不会重复插入。构建验证 chunk ID 和条目数；不完整索引会失败并要求选择新的根目录，不删除或覆盖旧数据。更新来源后先构建、评测，通过后再重启证据入口。回滚使用旧语料/代码版本及旧索引目录；不要手工覆盖正在使用的索引。

## 与同事 feature/rag 的兼容

本功能分支基于 `origin/feature/rag` 的 `9902806`，复用了同事的路径验证逻辑，保留自动入库修复。已实测独立空库首次初始化导入 180 行，再次初始化仍为 180 行，检索有结果；其 11 项测试通过。

两种入口明确区分：

- `python run_web.py`：保持原有默认知识库，使用 `MEDIX_DB_PATH` 和同事的默认集合自动初始化。
- `python run_kb_demo.py`：设置 `MEDIX_KB_MODE=evidence`，使用独立来源证据库及 `MEDIX_EVIDENCE_ROOT`，不会把旧版 180 行样例迁入证据集合。

同事提供的手工修复命令仍有效：`python knowledge/scripts/migrate_legacy_db.py`。迁移和普通项目启动必须使用相同 `MEDIX_DB_PATH`；目标必须是独立 V3 目录，不能指向 `knowledge/data/milvus_lite.db`。证据库不依赖这条迁移命令。

普通 `MedicalKnowledgeBase()` 无参数调用在显式 evidence 模式下返回证据实现，现有技能与研究工作流沿用 `search()` 接口；显式传入自定义数据库参数时仍保留原类行为。新资料主要是科普，`clinical_guideline`、`disease_classification` 类型可能没有结果，不用旧的未核实样例补齐。

建议先将同事 `feature/rag` 合入 main，再合入本分支自己的功能提交。新增核心代码集中于 `knowledge/`，共享改动仅为工厂入口、网页 API/UI 和研究来源格式。未修改配置密钥、Agent 路由、共享上下文或原始数据库；不包含“改造前后对比”。

## 检索与接口

按标题/段落切分，用 BGE tokenizer 限制含标题块最长 384 tokens，长段落按句子边界拆分并最多重叠 48 tokens；保存 Markdown 原文字符区间。中文分词使用 jieba，关键词检索使用 rank-bm25。语义和关键词各召回最多 10 个候选，按 RRF 融合，余弦相似度至少 0.4，内容去重，默认返回 3 段。

这是小型显式覆盖库：按来源主题和少量医疗术语做范围检查，库外问题不因偶然的向量相似度而返回证据。此规则会保守拒绝未覆盖的同义表达，不承诺通用医疗分类。具体用药、剂量、停换药与联合用药问题走保守提示规则，不进行个人剂量计算。

- `retrieve(query, top_k=3, filter_type=None)`：返回 `status`（`ok/no_results/needs_information/error`）、`hits`、`message`、`trace`。
- `search()`：兼容旧技能；错误抛出异常，无结果返回空列表。
- `GET /api/knowledge/catalog`：来源清单、版本和片段数。
- `GET /api/knowledge/retrieve?q=...`：无 Key 检索，包含来源和检索过程，查询仅接受 1–8000 字；不落盘查询。仅在 evidence 模式就绪后可用。
- `GET /api/health`：增加 `mode=evidence`、`source_documents` 和 `version`。
- 聊天结果增加 `retrieval`、`retrieval_status`、`generation`、`invalid_citations`，来源包含完整证据、机构、日期、原始 URL、原文位置和哈希。

证据提供给模型时使用完整片段与编号，模型不得把资料内指令作为指令执行。无效编号会被替换并返回记录；编号合法不等于结论有依据，仍需人工核对答案。检索分数和融合分数均不是医学可信度。风险与症状技能仍有其既有规则判断，不应把它们描述为经知识库临床认证。

## 验证与路演

```powershell
python -m unittest knowledge.test_bootstrap knowledge.test_evidence web.test_web -v
python knowledge/scripts/evaluate_evidence.py
```

评测集为 `knowledge/evaluation_cases.json`：20 个库内问题、5 个库外问题、5 个用药信息不足问题。命中要求 top-3 中存在预期来源，且片段包含预先标注的证据词；不是答案准确率，也不是独立医疗基准。脚本同时验证全部 chunk 的 token 预算、原文位置、唯一 ID 和索引条目数。结果写入忽略提交的 `verification_evidence.json`，交付记录保存在 `docs/evidence-evaluation.json`。本机未配置 API Key，真实模型回答质量未验证。

2026-10-29 本机交付验证：27 项回归测试通过；库内 Hit@3 为 20/20，库外与信息不足各 5/5，预热检索 p95 为 180.3 ms。重复构建条目数仍为 71；网页实际完成无 Key 聊天原文返回、引用点击、来源展开、高亮及 390px 窄屏无横向溢出检查。延迟为本机固定语料结果，不是通用性能承诺。信息不足项验证的是规则提示，不是模型回答质量。

三分钟路演顺序：

1. 打开知识库，输入“家庭测量血压选择什么血压计”，展开检索过程，点击片段，核对机构、日期和原文位置。
2. 输入“口服补液盐配制时有哪些常见错误”，点击证据，展示关键词高亮和官方原始发布链接。
3. 输入“三岁孩子发烧布洛芬吃多少毫升”，展示知识库不从泛化科普计算个人剂量；再输入库外问题，展示资料不足。

若已配置图文与工具调用模型，可改在聊天区展示带编号的真实生成回答；无 Key 时只展示原文检索，不能将其宣称为模型问答成功。路演前预热并检查 `knowledge=ready`，本地断网仍可检索和展开证据，外部原文链接和模型生成需要联网。

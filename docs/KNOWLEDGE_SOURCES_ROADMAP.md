# 权威医疗数据源扩展调研

核对日期：2026-10-30。本清单是后续接入建议；以下新增资源尚未入库。权威发布机构、证据类型、适用地区和复用许可需要分别记录，不能用机构名称代替质量审核。

## 按当前 demo 的收益排序

| 优先级 | 来源与官方入口 | 用途及接入方式 | 边界与许可 |
|---|---|---|---|
| P0 | [国家卫健委：高血压等慢性病营养和运动指导原则（2024）](https://www.nhc.gov.cn/ylyjs/gzdt/202407/256b4eb8398440a8811344c7be50a333.shtml) | 优先补高血压、糖尿病饮食与运动；人工核对附件，按疾病、营养/运动章节解析 | 中文、国内适用；公开附件不自动等于可任意再分发，逐份核查使用条件 |
| P0 | [国家药监局数据查询](https://datasearch.nmpa.gov.cn/datasearch/search-help.html) | 核对国内药品批准信息，关联具体厂家、剂型、规格及批准文号；优先人工挑选路演药品 | 查询库不能当作全部药品完整说明书的开放下载接口；未核实批量 API 或再分发授权。完整说明书应另从可核验发布渠道取得 |
| P1 | [DailyMed API](https://www.dailymed.nlm.nih.gov/dailymed/app-support-web-services.cfm) / [说明](https://dailymed.nlm.nih.gov/dailymed/about-dailymed.cfm) | NLM 的美国上市标签资源；用 SETID、版本及更新时间锁定具体 SPL XML，按禁忌/警告/用法等结构切分 | 包含提交给 FDA 的不同类型标签，不可一概标成已获 FDA 批准；不替代中国核准说明书。逐项核对内容和使用条款，不对全部图文统一宣称公有领域 |
| P1 | [MedlinePlus XML](https://medlineplus.gov/xml.html) / [内容使用规则](https://medlineplus.gov/about/using/usingcontent/) | NLM 患者教育主题摘要和链接，适合扩展常见病、检查解释；XML 有利于稳定增量导入 | 主题摘要等指定板块可复用并注明来源；百科、药品等第三方授权内容有不同限制。主要为英语/西语，中文翻译需另审 |
| P1 | [WHO 出版物与版权](https://www.who.int/about/policies/publishing/copyright) | 精选有明确版本的指南、患者教育文件，优先官方中文版本 | 很多出版物使用 CC BY-NC-SA 3.0 IGO，须逐份确认、署名及遵循非商业/相同方式共享等条件；第三方图表例外，改编/翻译需标明非 WHO 制作 |
| P2 | [PMC Open Access Subset](https://pmc.ncbi.nlm.nih.gov/tools/openftlist/) | 补少量经过筛选的指南、系统综述；使用允许复用子集及官方获取渠道，保留 PMID/PMCID/DOI 与文章许可 | PMC 可阅读不等于全文可任意复用；按篇筛选许可、研究设计、撤稿状态和发表时间。论文不是直接面向患者的诊疗指令 |
| P2 | [MeSH 下载](https://www.nlm.nih.gov/databases/download/mesh.html) / [条款](https://www.nlm.nih.gov/databases/download/terms_and_conditions_mesh.html) | 医学主题词、上下位关系和英文同义词，用于查询扩展与主题标注；作为术语索引单独存储 | 不是治疗依据；注明 NLM 与数据版本，翻译文件有独立条款，不能默认包含授权的中文映射 |
| 暂缓全文接入 | [NICE 条款](https://www.nice.org.uk/terms-and-conditions) | 可先保存指南标题、链接和版本，帮助人工挑选 | 英国以外使用其内容存在额外许可限制；本中国 demo 不应直接批量复制或构建全文检索库 |

## 建议下一批最小数据包

先补 4–8 份国内慢病营养与运动原文，再选 3–5 个 demo 药品的具体制剂说明书。若国内说明书无法合法稳定取得，就维持“缺少核准说明书”提示；DailyMed 只作为明确标注“美国标签”的独立演示集合，不自动回答国内剂量问题。不建议为了数据量整库导入论文。

每份文档增加：`evidence_kind`、`jurisdiction`、`language`、`audiences`、`published_at/updated_at`、`version`、`license/license_url`、`source_url`、`content_sha256`、`review_status`；说明书额外保存通用名、厂家、剂型、规格、批准文号或 SETID。缺项应显示未知，不能补造。新增字段和适配器属于下一批工作，当前没有宣称已经实现。

按证据类型分块：指南保留推荐条款及限定条件，说明书按标准章节切分并继承产品身份，表格保留行列标题和单位。检索先筛地区、人群和产品，再做混合召回及重排；若冲突则并列来源及版本，不把不同适应证或制剂的剂量融合。

每批接入至少新增库内命中、无覆盖、人群不匹配、过期版本、地区/产品冲突测试。对外展示完整来源链及资料缺口即可，无需扩大成临床诊断系统。

## GitHub / Hugging Face 专业语料筛选（2026-10-30）

本轮核对项目 README、数据卡及许可说明，没有下载全集、修改索引或验证新增语料的检索效果。以下顺序是结合本项目可追溯证据展示、中文提问和小组路演规模作出的工程建议。

| 选择 | 内容及获取入口 | 当前项目建议 | 已核实的限制 |
|---|---|---|---|
| **首选小样：MedQuAD** | [GitHub](https://github.com/abachaa/MedQuAD)，XML 医疗问答；项目描述为来自 12 个 NIH 网站的 47,457 对问答，含主题、同义词及医学概念标注 | 从有答案、原始链接可访问的疾病教育子集挑选，再回源核对；适合展示中英跨语言检索和来源证据卡 | 英文，历史快照需检查更新时间。仓库 [许可](https://github.com/abachaa/MedQuAD/blob/master/LICENSE.txt) 为 CC BY 4.0；[README](https://github.com/abachaa/MedQuAD/blob/master/readme.txt) 明确因版权移除了 A.D.A.M.、药品、草药/补充剂三个子集的答案，不应自行补抓这些受限答案 |
| **专业指南候选：Meditron Guidelines** | [HF 数据](https://huggingface.co/datasets/epfl-llm/guidelines)、[采集处理代码](https://github.com/epfLLM/meditron/tree/main/gap-replay/guidelines)，约 3.8 万条公开英文资料，含 source/title/clean_text/raw_text/url | 先筛与现有病种相关、许可可确认的 WHO/CDC 等原始来源，再筛地区、人群与现行版本；借鉴清洗流程 | 数据卡标注 common-crawl 条款，不是对全部原文的统一版权授权；不同来源条款仍须核对。知识截止标注 2023-08，另有 2023-12 PubMed 增补，不能称为最新指南全集；不能把其中 NICE 全文默认用于国内 demo |
| **中文问法与探索集：Huatuo26M-Lite** | [HF](https://huggingface.co/datasets/FreedomIntelligence/Huatuo26M-Lite)、[上游](https://github.com/FreedomIntelligence/Huatuo-26M)，约 17.8 万条中文 QA，带科室、相关疾病等字段，数据卡标注 Apache-2.0 | 挑 100–300 个非个人化问题作问法/主题覆盖测试，答案重新对齐现有权威原文；暂不把其答案混进主证据集合 | Lite 经过清洗、改写；浏览器所示字段没有逐条发布机构、原文 URL、更新时间。不能从样本 score 或数据卡许可推导出医学审核及原始内容授权 |
| **中文百科备选：Huatuo encyclopedia QA** | [HF](https://huggingface.co/datasets/FreedomIntelligence/huatuo_encyclopedia_qa)，训练 split 约 36.2 万条，questions/answers 字段；数据卡标注 Apache-2.0 | 用作疾病主题清单和问题候选，优先直接取上游，避免重复导入二次打包版本 | 示例含未绑定具体制剂身份的剂量回答，缺少当前证据卡所需逐条来源信息；不适合作为核准说明书替代品 |
| **借鉴 RAG 工程：MedRAG** | [代码](https://github.com/gzxiong/MedRAG)、[Textbooks](https://huggingface.co/datasets/MedRAG/textbooks)、[StatPearls 数据卡](https://huggingface.co/datasets/MedRAG/statpearls) | 借鉴章节标题继承、语料分组与检索评测；StatPearls 若确认许可后，可少量从原始 NCBI 来源接入 | Textbooks 为 18 本教材的约 12.6 万片段，数据卡没有提供足以核实每本教材再分发权利的说明。StatPearls 卡明确不能分发正文，HF 并非可直接下载的正文库，需自行从 NCBI 获取并核对使用条件 |
| **评测集：CMB** | [GitHub](https://github.com/FreedomIntelligence/CMB)、[HF](https://huggingface.co/datasets/FreedomIntelligence/CMB)，CMB-Exam 考试题与 CMB-Clin 74 个病例，数据卡标注 Apache-2.0 | 后续抽与覆盖病种相符的问题做独立评测；测试答案不入检索库 | 主要用于医学考试/病例能力评测，不是患者教育证据库；未覆盖问题应允许资料不足，不能拿考试准确率代替当前引用可靠性 |
| **检索研究备选：cMedQA2** | [GitHub](https://github.com/zhangsheng93/cMedQA2)，10.8 万问题、约 20.4 万答案 | 研究中文答案选择、难负例及口语问法，不优先导入主库 | 作者限定非商业研究；社区问答与指南原文的证据等级不同 |
| **暂不整库导入：MMedC / medical** | [MMedC](https://huggingface.co/datasets/Henrychur/MMedC)、[shibing624/medical](https://huggingface.co/datasets/shibing624/medical) | 仅作预训练语料处理和数据来源线索参考 | MMedC 为 25.5B tokens 的多语混合语料，含中文，但为预训练设计且原始来源/教材许可需逐项核查；其卡说明英文教材因版权不随库提供。medical 将百科、教材、SFT、偏好数据打包，含上游重复内容；统一训练格式不等于具备可追溯证据元数据 |

不要将 [CMeKG_tools](https://github.com/king-yyf/CMeKG_tools) 的 MIT 工具代码许可误认为完整知识图谱数据授权。它可用于分词、实体识别与关系抽取探索，但不能凭此认定已获得权威图谱正文。资源目录如 [awesome_Chinese_medical_NLP](https://github.com/GanjinZero/awesome_Chinese_medical_NLP) 可继续发现候选，本身不是已审核语料包。

## 适合当前规模的组合

建议保留国内权威原文为主库，先做 **20–40 份可回源的 MedQuAD 相关资料 + 10–20 份逐份核验的专业指南** 的候选小样；优先高血压、糖尿病、过敏性鼻炎和基础用药信息。没有合适许可/现行版本的资料就跳过，不为满足数量降低标准。

Huatuo-Lite 只供中文提问候选，经过人工改成一般健康问题再使用；CMB 保持独立评测。此组合可展示“中文提问 → 原文证据 → 标注非官方中文释义 → 原始机构/版本”，英语指南与美国药品标签必须显示语言和适用地区。上述跨语言效果需另外测试，不能直接沿用现有 39 题通过率。

接入时先实现 XML/JSONL 适配器、来源许可清单和语言/地区元数据，再挑选并冻结 revision。不能直接复用第三方预切 chunk 的位置编号冒充本项目原文区间；保留原文后重新按当前 tokenizer 切分、生成 ID 和索引。新建独立证据版本，评测通过后再切换服务。

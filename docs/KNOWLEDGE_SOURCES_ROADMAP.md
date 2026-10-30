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

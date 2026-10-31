# 网页搜索与 ResearchAgent

默认 `MEDIX_SEARCH_PROVIDER=deepseek`。启动前提供 `DEEPSEEK_API_KEY` 或独立的 `DEEPSEEK_SEARCH_API_KEY`，密钥只留在服务器环境或忽略提交的本地配置。聊天模型名与搜索接口独立。`deep_research` 先规划子查询，再异步访问官方 Search 并结合当前本地知识库，最后由模型综合。`clinical_guideline` 与 `search_knowledge` 为本地检索。

配置与价格见 `.env.example`。官方 Search 每次成功且非空结果的调用默认0.005元；默认换算为5关怀点，不含规划、综合与回答生成的Token消耗。数据库已有钱包的兑换比例保持原值。价格快照进入调用记录，修改配置不会追改历史。搜索失败不隐式切到DDGS，不自动重试付费请求；需旧后端时显式设为ddgs。

搜索链接和长摘要完整返回Worker；来源按URL去重。日期与权威性标签来自供应商，不等于医学审核。空结果不合成无依据报告；失败不标为完成。请求被客户端中断或无法确认结算时，保留本次搜索额度待核对，不虚报为免费或已精确结算。

验证：`python scripts/verify_research.py`；`python scripts/verify_integration.py`。离线用例不访问真实模型、搜索服务或正在运行的账号库。`python scripts/check_research_live.py --with-model --report /tmp/research-live.json` 会调用公开搜索及已配置模型并产生供应商费用，使用隔离数据目录；可不加`--with-model`只验证公开搜索。

官方说明：https://api-docs.deepseek.com/zh-cn/guides/search/

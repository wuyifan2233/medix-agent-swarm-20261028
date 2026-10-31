# 本地合并 main_copy 记录

日期：2026-10-31。工作区：E:/workspace/medix-agent-swarm-20261028。当前本地分支仍为feature/knowledge_db。

## 合并范围与结果

- 本地原HEAD：1f8c777d2adf832bc47dd0b99e1ce9afe7b61fb0。
- 已获取并快进至origin/main_copy：3f980a5（Document team setup, unified architecture and feature acceptance workflow）。
- merge-base等于原HEAD，main_copy已经完整包含本地全部已提交代码。因此使用merge --ff-only，无代码分叉冲突，不新增合并提交。
- 合并前仅暂存保护AGENTS.md和knowledge/DESIGN.md的未提交修改，没有收走或覆盖其他未跟踪产物。恢复stash时出现下述两处文档冲突。
- 当前未解决Git冲突为0。两份本地说明已标记解决并暂存；没有提交新commit，没有推送。

## 逐项冲突处理

| 文件 | 实际冲突 | 处理及依据 |
|---|---|---|
| AGENTS.md | 上游保留“正文不能加入交付包或Git”，本地补充了用户明确授权的私有开发迁移例外 | 以main_copy完整AGENTS为底稿，保留顶部统一账号、业务数据库、启动与验收规则，仅替换来源交付这一行，恢复私有包仅本机生成、排除密钥、不推送Git的说明。该例外有当前用户的明确授权，无需猜测功能选择。 |
| knowledge/DESIGN.md | 上游规范化正文并追加统一启动、mini后备及分支验收说明，本地在原文件末尾新增第16节迁移实测；换行差异使Git把第10节以后显示为大块冲突 | 先校验本地版本在换行归一化后等于原HEAD完整正文加第16节，证明本地没有另改功能设计。保留main_copy全文，再追加本地第16节。没有将本地旧稿整块覆盖回去，也没有重复第10至15节。两方不同工作区/历史时点的验收记录均保留，不把它们改写成新集成版已验证。 |

不确定的代码行为没有手动选边：除两份说明恢复外，全部业务代码保持main_copy原样。没有为了让测试通过修改模型、鉴权、短信或渠道行为。

## 校验结果

- 112个相对原HEAD变更的Python文件通过AST语法检查。
- 24个web/static目录JavaScript文件通过node --check。
- 知识库核心离线回归32/32通过：knowledge.test_initialize、test_embeddings、test_reranking、test_bootstrap。
- 原.env.local、语料manifest、指定最终PPT、私有迁移ZIP及当前Milvus数据库6个文件，共10个受保护文件的SHA256在操作前后一致。未读取或显示密钥正文。
- 未启动或重启新的集成网页，未运行真实外部API验证，未迁移现有账号/业务数据库。原运行进程不会因Git更新自动加载新代码。

## 待确认，未擅自修复

以下是验证/环境差异，不是仍存在的Git冲突标记。

1. 集成依赖：本机medix是Python3.12的原知识库环境，缺pwdlib、alembic、alibabacloud_dypnsapi20170525。没有安装整套requirements.integration.txt、降级或替换现有torch/transformers等模型依赖。新分支指南给出的集成环境主要验证于Python3.10；两者需另做环境验收。
2. 模型配置优先级：tests.test_deepseek_config中的test_deepseek_overrides_openai_without_changing_memory_key期望thinking=enabled，实际disabled；test_openai_fallback_remains_available期望gpt-4.1-mini，实际deepseek-flash。不能在未确认统一模型方案和本机配置优先级前改写config.py或.env.local来消除断言。
3. 微信登录状态：wechat.test_bridge.BridgeTests.test_login_keeps_token_off_the_page期望waiting，实际error。其他微信回归同时遇到缺alembic；尚未确定该失败是否完全由缺依赖引起，不修改微信状态机。

完整集成脚本本次报告Ran163、failures=3、errors=33；部分测试模块因缺依赖未能加载，163不是完整集成用例总数。不得宣称全组集成回归通过。脚本使用隔离业务库knowledge/.local/merge-main-copy/isolated-app.db，日志在同目录integration.log。

## 备份与可回溯性

- 本地未提交修改原件：knowledge/.local/merge-main-copy/before/。
- 原始二进制patch及受保护文件指纹：knowledge/.local/merge-main-copy/。
- 保留的stash：784c5bfab537d93036bfe068ce56d9a09f13a662（创建时为stash@{0}，说明pre-main_copy private migration documentation）。尚未drop。
- deliverables/、knowledge/local.zip、docs/private-migration-validation.json等原有未跟踪文件未纳入本次提交。

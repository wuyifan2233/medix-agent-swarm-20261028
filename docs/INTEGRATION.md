# main_copy 集成记录

本分支从 main 的 b0dcf55 创建。成员分支保持不变，集成修复只提交 main_copy。

## 固定的交付版本

| 模块 | 分支 | 提交 |
|---|---|---|
| 账号 | feat/auth-permissions | 5b747d2 |
| 个性化 | feature/health-profile-evolution | bef7325 |
| RAG | feature/rag | 9902806 |
| 知识库 | feature/knowledge_db | 1f8c777 |
| 病例 | feature/mllm-report-analysis | 4fae7c9 |
| 记忆 | memory | bafe845 |
| 提醒及渠道 | feature/scheduled-reminder | 2a3b6c8 |

## 集成约定

- 只保留手机号账号认证；旧用户名接口仅供显式开启兼容模式的自动测试。
- 所有业务数据统一使用账号数据库 `MEDIX_DATABASE_URL`，默认当前工作区 `.medix-data/app.db`。不读取成员原工作区的账号数据库。
- 模块获取当前用户用 `require_user`。业务归属使用 `users.id`，人物、病例和会话是其下的不同维度。
- 向量索引和 Mem0 保留独立用途，不与关系数据库合并，不自动迁入旧匿名数据。
- 微信/QQ 是消息渠道，不提供网页第三方登录。绑定必须验证渠道身份并关联当前账号。
- 成员数据库不拼接、不覆盖；需要保留的数据另行明确迁移。

## 合入顺序与处理结果

1. 最新手机号认证作为身份基础，覆盖旧用户名方案。
2. 健康档案、档案演进、回答偏好；迁移接为 08–10。
3. RAG 和证据知识库；保留公共索引及引用展示。
4. 多模态病例分析；私有病例、事实和修订迁入业务库，迁移 11。
5. 长短期记忆；本人/亲友与虚构演示分开，迁移 12、14。
6. 定时提醒与微信/QQ；提醒、送达和渠道绑定迁入业务库，迁移 13。
7. 统一依赖和启动；主分支及成员原分支均未修改。

提醒分支与 main 没有共同祖先。首轮曾选取功能模块；本轮已用允许无共同祖先的真实 Git merge 完整纳入 2a3b6c8，并逐文件核对其全部40个变更。冲突依据共同来源 b0dcf55 的文件内容及当前集成方案解决；账号鉴权和统一业务库不退回旧实现。知识库最新 1f8c777 同样已建立完整合并关系。详见 [逐文件核对记录](BRANCH-INTEGRATION-AUDIT.md)。

## 数据库到底怎么统一

只有一份 SQLite **业务数据库**：默认 `.medix-data/app.db`，由 Alembic 自动升级到单一 head `20261030_14`。包含账号、档案、偏好、病例、记忆、本地提醒、送达、渠道绑定。导入模块复用 `storage/business.py`，不再读取各成员的病例/提醒 SQLite 文件。

- `MEDIX_DATABASE_URL` / `MEDIX_DATA_DIR`：业务数据。
- `MEDIX_DB_PATH` / `--db-path`：公共医学资料的向量索引，独立目录，不能指向业务 SQLite 文件。
- `MEM0_API_KEY`：可选云端长期记忆服务。命名空间包含环境、账号和人物。
- 同学的本机数据库不会被 Git 带过来，也不会自动搬入。新环境第一次启动是空账号库；测试数据或需要保留的资料应另做明确迁移。
- 本地用户外键关联数据随注销清理；远程 Mem0 的物理清除不作为已完成项目，新注册 UUID 不会再访问旧账号记忆。

## 拉取后怎么启动（Windows）

当前正在运行的8767预览使用 `.medix-data/integration`，其账号来自原工作区数据库的只读备份，已升级并保留原账号ID；最初的合成账号测试库在 `.medix-data/ui-check`，不作为正式预览账号来源。这些数据库与本地短信配置均不在Git中。

本机实测 Python 3.10；其他 Python 版本需自行验证对应轮子兼容性。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.integration.txt
Copy-Item .env.example .env.local
# 编辑 .env.local：填写自己的模型配置、稳定的环境 namespace。
# 短信密钥可按 docs/SMS-SETUP.md 放进忽略提交的 .env.sms。
.\.venv\Scripts\python.exe run_web.py
```

访问 `http://127.0.0.1:8765/`。启动自动建库/升级，无需另外启动 MySQL、Redis 或 Qdrant。首次运行 BGE 检索需下载公开模型，或通过 `HF_HOME` 使用已有缓存；默认缓存位于项目 `.medix-model-cache`。

证据库入口 `python run_kb_demo.py` 现在复用相同的本地配置、账号库和启动处理，默认8766；`--prepare-only` 保留。新证据库正文未随 Git 提交，首次准备可能需要较长时间联网获取。默认普通入口仍使用旧样例向量库；`MEDIX_KB_BACKEND=auto` 在 Milvus 不可用时用明确标识的文本后备，`milvus` 强制向量库、`mini` 显式文本检索。证据模式不自动降级。

并行预览：`python run_web.py --port 8767 --data-dir .medix-data/preview`。启动器为不同端口选择独立向量目录，避免抢同一索引；账号数据库由 data-dir 单独指定。不要用打开 index.html 文件的方式预览。

`.env.local`、`.env.sms`、数据库、模型和渠道凭证不提交。当前集成工作区是 `D:/Code/xiaoyi/output/main_copy`；原 `D:/Code/xiaoyi` 保留认证分支。

## 微信/QQ接入边界

这是消息渠道，不是用微信或 QQ 登录网页。先登录 MediX 手机号账号，连接结果绑定其 `user.id`，不需要再给机器人独立绑定手机号。

- 本地桥接每个渠道只有一个物理连接账号；不是无限人数同时扫码的公共机器人平台。其他 MediX 账号不能接管已有连接。
- 微信仅接收扫码确认身份的私聊消息；QQ好友需回复一次性绑定码，确认前不开放医疗问答与推送。
- QQ依赖本机 QQ 与 SnowLuma/OneBot 环境；微信依赖该分支使用的 iLink 接口。是否可用仍受客户端、网络和平台限制。
- 停用账号不再产生新提醒或发送已排队的渠道内容。重启恢复提醒数据；渠道凭证保留，但需在页面点击连接后启动桥接，避免未确认就对外发消息。

## 已验证与待联调

- 完整补合后的整套离线回归：327 项通过，运行 `python scripts/verify_integration.py`。
- 包含真实 Session/Cookie/CSRF 的双账号检查、私有病例/记忆越权、提醒归属、停用、注销外键清理、QQ绑定码确认。
- 业务数据库可空库升级、重复升级，并能重新创建服务后读取原提醒与渠道归属。
- 统一依赖在 Windows/Python 3.10 下完成 pip 全新环境解析（dry-run），无解析冲突；当前运行环境实际测试通过，未声称已在全新电脑安装验收。
- 实际本地 BGE/Milvus 检索：180条资料，查询返回3条。
- 浏览器：手机号密码登录、重启保留会话、设置弹窗；1366×768及390×844检查，窄屏无横向溢出；控制台未发现错误。
- 用户已确认接回本地短信配置后可正常登录；密码登录不调用短信提供商有专项验证。聊天/视觉模型、新证据库正文构建、Mem0、微信/QQ外部收发仍须独立配置联调；代码完整合并不等于这些外部服务均已验证成功。
- 最终变更后的定向补验：29项存储/启动/记忆、23项渠道与隔离，以及渠道切换竞态用例通过；全部前端 JavaScript 语法检查通过。

main_copy 验收后再由组长决定是否合入 main；本轮没有执行该操作，也没有推送覆盖成员分支。

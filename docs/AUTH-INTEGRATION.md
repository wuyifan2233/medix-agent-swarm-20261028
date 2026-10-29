# 用户认证与基础权限：实现及模块对接

本分支实现网页账号认证和基础角色管理。认证身份来自服务端 Session，不接受前端或模型声明的用户身份。业务模块必须检查资源归属；接入登录不等于私人知识库、病历等功能自动具备隔离能力。

## 1. 技术和运行方式

- FastAPI `Depends`；SQLAlchemy 2.x；SQLite；Alembic 迁移。
- `pwdlib[argon2]` 的 Argon2id 密码哈希。密码 15–128 字符，登录兼容已有密码长度。
- `secrets.token_urlsafe(32)` 生成 256 位随机登录秘密；数据库仅保存 SHA-256 哈希。
- HttpOnly、SameSite=Lax Cookie；生产使用 Secure 和 `__Host-` 前缀，无 Domain。
- 服务端每次读取有效登录和用户状态；空闲 30 分钟或创建后 12 小时过期。
- CSRF 令牌由登录秘密做域分离哈希派生，服务端保存令牌哈希。令牌只在前端内存保留，同一登录下各标签页稳定。获取 CSRF 令牌必须先通过登录认证。
- 同源写 API 必须有允许的 Origin、`Content-Type: application/json`、`X-Medix-Request: 1`。登录后的写 API 另需 `X-CSRF-Token`。
- 不启用跨源 CORS；浏览器页面和 API 通过同一个源提供。

环境变量由进程读取，`.env.example` 不会自动加载。先使用项目原有 Python 3.12 虚拟环境安装 `requirements.web.txt`，然后：

```powershell
# 在仓库根目录，用同一个虚拟环境的 Python 执行：
python -m storage.migrate
python scripts/create_admin.py
python run_web.py
```

管理员脚本交互式输入密码，不存在默认管理员、默认密码或注册首人自动提权。
`run_web.py` 启动时也会执行未应用的迁移，然后才启动知识库预热；账号功能不依赖模型 API 或向量模型。
也可沿用 `start_web.ps1`。打开 `/login` 注册普通用户或登录，`/account` 修改密码、退出、管理用户。

开发配置默认：

| 配置 | 默认值及含义 |
|---|---|
| `MEDIX_ENV` | `development`；上线必须设为 `production` |
| `MEDIX_DATA_DIR` | 仓库 `.medix-data/`，默认账号数据库在其中 |
| `MEDIX_DATABASE_URL` | 可选，覆盖数据库地址；例如 `sqlite:///D:/medix-data/app.db` |
| `MEDIX_ALLOWED_ORIGINS` | `http://127.0.0.1:8765,http://localhost:8765`，逗号分隔 |
| `MEDIX_ALLOW_REGISTRATION` | 开发默认 true，生产默认 false |
| `MEDIX_IDENTITY_NAMESPACE` | 默认 `local`，每位开发者设置独立稳定值，如 `dev-leon` |

生产必须显式配置 HTTPS origins；应用据此限制 Host。生产启动仍需要部署者配置 HTTPS 终止、监听地址以及受信代理。默认启动器只监听本机。代理不能无条件信任外部 `X-Forwarded-For`；限流身份来自受信配置处理后的 `request.client.host`。当前适用于单机演示/单个后端进程，不能仅通过增加 Uvicorn workers 扩容：聊天 jobs/contexts 仍在进程内，Milvus Lite 也有现有并发约束。

## 2. 你的模块提供的接口

| 方法和路径 | 说明 |
|---|---|
| POST `/api/auth/register` | username、password、display_name；只能创建 user，未知字段拒绝；不自动登录 |
| POST `/api/auth/login` | username、password；设置 Cookie，返回 user 和 csrf_token |
| GET `/api/auth/me` | id、username、display_name、role |
| GET `/api/auth/csrf` | 当前登录的 csrf_token，供刷新页面后初始化 |
| POST `/api/auth/logout` | 撤销当前登录，清 Cookie；空 JSON `{}` |
| POST `/api/auth/logout-all` | 撤销该用户全部登录，清 Cookie；空 JSON `{}` |
| POST `/api/auth/change-password` | current_password、new_password；校验原密码，成功撤销全部登录 |
| GET `/api/admin/users?offset=0&limit=20` | admin，分页返回普通用户和管理员基本资料，不返回凭证哈希 |
| PATCH `/api/admin/users/{id}/status` | admin，`{"is_active":false}`；只管理普通账号；停用撤销全部登录，重新启用不恢复旧登录 |

错误：401 登录无效；403 来源/CSRF/角色拒绝；404 资源不可见；409 用户名不可用；413 认证请求超过 16 KiB；422 参数错误；429 限流。
参数校验响应只返回字段位置，不回显输入密码。用户名为 3–32 位 ASCII 字母数字下划线，统一小写，展示名称允许中文。

登录限流使用 SQLite `auth_attempts`，按 15 分钟窗口统计：每 IP 30 次登录、每用户名 10 次登录；注册每 IP 10 次；改密每 IP/用户 10 次。统计包含成功和失败尝试，避免可被绕过的错误计数分支。没有永久锁号。限流表在下一次认证写请求时清理过期记录；生产仍需网关级请求/连接限流。

## 3. 后端统一接法（必读）

```python
from fastapi import APIRouter, Depends, HTTPException
from auth.dependencies import require_user, require_admin
from auth.schemas import CurrentUser

router = APIRouter()

@router.get('/api/records/{record_id}')
def read_record(record_id: str, user: CurrentUser = Depends(require_user)):
    record = record_repository.find_owned(record_id, owner_user_id=user.id)
    if record is None:
        raise HTTPException(404, '记录不存在。')
    return record

@router.delete('/api/records/{record_id}')
def delete_record(record_id: str, user: CurrentUser = Depends(require_user)):
    # require_user 自动检查写请求的 CSRF；仍需带条件删除，不能只按 ID 删除。
    if not record_repository.delete_owned(record_id, owner_user_id=user.id):
        raise HTTPException(404, '记录不存在。')
    return {'deleted': True}

@router.post('/api/knowledge/public/reindex')
def reindex(user: CurrentUser = Depends(require_admin)):
    return public_knowledge_service.reindex()
```

以上 repository/service 是对接示意，由各业务负责人实现。`CurrentUser` 只有 id、username、display_name、role，不包含密码、Session 或健康档案。

- `require_user` 对 GET/HEAD 做认证，对 POST/PUT/PATCH/DELETE 同时做 CSRF 校验；管理角色通过 `require_admin`。
- 将 router 注册进 `web/app.py` 的 app，沿用全局来源检查。新建独立 FastAPI app 必须自行安装同样的安全中间件和异常处理。
- 不接收请求正文 `user_id` 作为可信身份；模型生成的 user_id 同样不可信。
- 普通资源始终按 `(resource_id, owner_user_id)` 查询/更新/删除；批量接口、导出、下载、流式重连也不能漏。
- 管理员不会自动获得其他用户私人数据的访问权；个人资源接口仍按所有者过滤。
- 不把用户状态放进模块全局变量、知识库单例或模型提示词后依赖模型执行权限。
- 第三方机器人回调不适用浏览器 Origin/CSRF 机制。需要独立路由前缀和平台签名验证；不要直接给现有 `/api/` 写接口加宽泛豁免。先验证平台账号绑定，再构造业务执行身份。

## 4. 前端统一接法

在业务脚本之前加载 `/assets/auth.js`，受保护页面 html 添加 `data-auth-pending`，样式中隐藏初始化前的内容。

```javascript
const user = await MedixAuth.ready;
const response = await MedixAuth.fetch('/api/records/123', {
  method: 'DELETE', body: '{}'
});
if (!response.ok) throw new Error(await MedixAuth.detail(response));
```

`MedixAuth.fetch` 自动携带 Cookie、写请求 JSON 头、自定义头和 CSRF 头；401 时清理页面并跳转登录。
不要自己读取 Cookie，不要把凭证或 CSRF 放在 localStorage。localStorage 中只有用于标签页通知的随机事件标记。
登录变化通过 BroadcastChannel 和 storage 事件通知其他标签页；页面从后退缓存恢复时重载，回到窗口时重新核对账号。模块应监听 `medix-signout` 清理自己的上传、预览、音频和轮询。

## 5. 各模块分工和必须接入的位置

| 模块 | 必须做的对接 |
|---|---|
| 会话持久化 | conversations.owner_user_id 关联 users.id；messages 通过 conversation 关联；所有历史读取/恢复/删除/导出先校验归属 |
| 病历分析 | 病历、附件、分析结果和分析任务记录所属用户；原文件不能通过静态目录公开；下载也鉴权 |
| 知识库 | 公共资料/私人资料明确区分；库、文档及每个向量分块持有归属和可见性；搜索前在向量库侧过滤已授权范围 |
| 长短期记忆 | 按 user + conversation 保存；Mem0 使用服务端提供的命名空间用户 ID，不允许账号路径回退到默认 medix_user |
| 个性化 | profile/preferences 使用 users.id 关联；此模块不重复保存角色或账号密码 |
| 用量费用 | 服务端按 user_id、job_id、conversation_id 归账；不相信前端传入的用户身份 |
| 流式输出 | 建立、恢复和读取任务流均鉴权并校验任务归属；长连接还需要明确过期/停用后的断流策略 |
| 机器人/推送/定时 | 验证外部账号绑定；任务保存所有者和目标；执行前重新检查账号状态、资源权限、绑定状态 |

当前网页接入已完成：

- `/api/chat` 和 `/api/jobs/{job_id}` 依赖 `require_user`。
- jobs 使用 `owner_user_id`；读不到别人的任务，响应不返回内部归属字段。
- contexts 使用 `web-{user_id}-{chat_id}`；相同聊天 UUID 在不同账号下互不共享。
- Mem0 身份为 `medix:{MEDIX_IDENTITY_NAMESPACE}:user:{user_id}`，同一账号跨登录保持稳定。
- 后台排队任务开始前检查账号是否启用；退出登录不会取消已经授权提交的分析任务，账号停用也不会强制中断已经运行的上游调用。后续取消/流式模块需另行实现。
- 私人知识库尚未实现。本分支仍检索原有共享公共医学资料，不应往当前无权限过滤的集合写入私人病历。

### 知识库和 Agent 的特殊约束

检索不只发生在 `web/app.py:analyze`。以下调用链也直接使用 `MedicalKnowledgeBase.search`：

- `.claude/skills/search-knowledge/script/search.py`
- `analyze-symptoms`、`assess-risk`、`recommend-lifestyle`、`disease-code`、`clinical-guideline` 的 script
- `research/deep_research_workflow.py`

知识库负责人应提供统一的权限检索服务，Agent 负责人把可信 actor/允许库范围绑定到每个请求的工具实例。模型只填写 query/max_results，不能填写 actor。权限过滤发生在取出分块之前，不允许全库检索后才在 Python 或提示词中删结果。

现有 `MedicalKnowledgeBase` 和多个 Skill 缓存的是全局单例，只能共享连接和模型，不能存 current_user_id。`SkillRegistry.execute` 还会把同步函数交给线程池，`web/app.py` 本身也使用线程池；优先显式传递不可变身份，不能假设上下文自动跨线程传播。

旧浏览器 Cookie 的任务和云端记忆不自动迁移到新账号，不应无条件认领。

## 6. 共同数据库和迁移规则

- 每个人的 SQLite 各自独立；提交模型、迁移和初始化脚本，不提交 `.medix-data`、上传文件或真实账号数据库。
- 统一使用 `storage.database.Base`；新表使用字符串 UUID 和 `users.id` 外键，开启 SQLite 外键约束。
- 新模块模型需在迁移 env 中显式导入，供 autogenerate 发现；不要创建第二套 Base 或在请求中 create_all。
- `alembic revision --autogenerate -m "..."` 生成后人工检查，再 `alembic upgrade head`。并行 PR 出现多个 heads 时由数据库负责人协调，必要时 `alembic merge`；禁止重写已经共享执行的迁移。
- SQLite 用于当前开发和单机演示；多进程生产迁移需要发布阶段独立执行，不能多个进程同时自动迁移。替换 PostgreSQL 时要重新验证并发限流事务与登录撤销竞态，不能只改 URL 就声称已支持。
- 迁移脚本没有演示账号或密码；创建管理员用独立脚本。数据库位置和账号身份命名空间应随演示环境稳定保留。

## 7. 验证与安全边界

```powershell
python -m unittest auth.test_auth web.test_web -v
```

测试使用独立临时 SQLite 和真实 Argon2id，不调用真实模型或 Mem0。覆盖迁移、密码/凭证哈希、Cookie、来源/CSRF、限流、退出/改密/停用撤销、管理员权限、任务归属和原有图片/上下文回归。

2026-10-29 本分支验证：28 项测试通过；Alembic 模型差异检查、回滚至 base 后重新升级通过；打包文件清单包含 auth/storage/scripts 和迁移配置，排除账号数据库及测试环境。真实浏览器已验证注册、普通用户登录、账号页改密后退出、管理员停用/启用账号与退出，检查桌面和 390px 手机布局。

本机可用验证环境为 Python 3.10.11、FastAPI 0.115.6、SQLAlchemy 2.0.36、pwdlib 0.3.1、Alembic 1.14.0，使用项目内 `.venv-auth`。原仓库文档指定的 Python 3.12 及完整依赖快照环境尚未复测；未调用真实模型、Mem0 或验证新增私人知识库功能。浏览器预览使用独立虚构账号数据库且关闭知识库预热，不能视为完整医学问答链路验证。

上线还需单独配置 TLS、备份访问控制、网关限流、监控和密钥管理；本分支没有提供 MFA、邮件找回、OIDC/SSO、医疗合规认证、完整审计后台或私人知识库实现。HttpOnly 限制读取 Cookie，不能让 XSS 失去所有攻击能力；保持安全 DOM 操作和 CSP，业务模块不能插入未经清理的 HTML。

参考：[OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)、[OWASP Authorization](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)。

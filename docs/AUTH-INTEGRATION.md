# 用户登录对接：按用户加载 profile 和记忆

## 这次只要做到什么

**登录模块告诉系统“当前用户是谁”；其他模块根据同一个 `user_id`，加载这个用户自己的 profile 和记忆。**

第一版不需要新增复杂的权限配置、组织架构或共享机制。账号管理已有的管理员角色直接复用即可。

注册及修改密码采用本项目规则：8–20 位，大写字母、小写字母、数字、特殊字符中至少包含三类。已有账号仍按原密码验证；此调整不改变用户 ID 或模块对接接口。

其他同学开始前，先同步包含 `auth/`、`storage/` 的认证分支代码。只拿这份文档、仍基于原版 main 开发，无法直接调用下面的接口。不要各自再写一套登录。

## 1. 登录模块已经提供了什么

| 能力 | 怎么用 |
|---|---|
| 获取可信的当前用户 | 后端使用 `Depends(require_user)`，拿到 `user.id` |
| 前端获取当前用户 | `await MedixAuth.ready`；未登录时结果为 `null` |
| 提醒用户登录 | `await MedixAuth.requireLogin()`；未登录会打开首页弹窗并返回 `false` |
| 前端调用业务接口 | 使用 `MedixAuth.fetch()`，自动处理 Cookie 和 CSRF |

`user.id` 是账号的稳定 UUID。同一账号重新登录，ID 不变；换账号，ID 就不同。

手机号验证码登录也沿用这个 ID。先在原账号设置中绑定手机号，之后用该手机号登录仍是原账号；其他模块无需区分登录方式。

**不要用用户名、浏览器 Cookie、聊天 ID 或前端传来的 user_id 代替它。**

## 2. profile 模块怎么接

保存和读取 profile 时，都使用后端拿到的 `user.id`。

建议字段：`user_id`（唯一，关联 `users.id`）、`profile_data`、`updated_at`。

下面是接口示意，`profile_store` 由负责 profile 的同学实现：

```python
from fastapi import APIRouter, Depends
from auth.dependencies import require_user
from auth.schemas import CurrentUser

router = APIRouter()

@router.get('/api/profile')
def get_profile(user: CurrentUser = Depends(require_user)):
    return profile_store.load(user_id=user.id)
```

保存 profile 的接口同样使用 `user.id`。前端只提交偏好等业务内容，不指定要保存到哪个用户。新用户没有 profile 时返回空配置或默认配置，不能返回其他用户的资料。

新增表复用 `storage.database.Base`，通过现有 Alembic 迁移创建；不要另建一套账号表。

## 3. 记忆模块怎么接

**长期记忆按用户分，短期上下文按“用户 + 会话”分。写入和读取必须使用相同规则。**

当前网页已经使用这些标识：

```python
# 当前用户：来自 require_user
user_id = user.id

# 短期上下文：不同用户即使传入相同 chat_id，也不会混用
session_id = f'web-{user_id}-{chat_id}'

# 长期记忆：namespace 来自服务端 MEDIX_IDENTITY_NAMESPACE 配置
memory_user_id = f'medix:{namespace}:user:{user_id}'
```

`web/app.py` 已将 `memory_user_id` 传给 `SwarmCoordinator`，后者再传给 Mem0。负责记忆的同学沿用这个身份，完成自己的保存、读取和删除功能即可。

注意三件事：

- 身份从后端传入，不能让模型或前端指定。账号路径缺少身份时，拒绝操作，不能回退到共享的 `medix_user`。
- 不把当前用户的 profile/记忆放进全局单例。用缓存时，缓存键也必须带用户标识。
- 每位开发者设置不同的 `MEDIX_IDENTITY_NAMESPACE`，例如 `dev-leon`；演示环境用固定值，如 `demo`，避免共用 Mem0 时混入开发数据。

## 4. 前端怎么接

首页已经加载 `auth.js`。业务按钮可以这样写：

```javascript
async function loadMyProfile() {
  if (!await MedixAuth.requireLogin()) return;
  const response = await MedixAuth.fetch('/api/profile');
  if (!response.ok) throw new Error(await MedixAuth.detail(response));
  const profile = await response.json();
  // 用 profile 更新本模块的页面
}
```

模块监听 `medix-signout`，清空旧用户的 profile、记忆展示和本地缓存；监听 `medix-auth-change`，在 `event.detail` 有用户时重新加载当前用户的数据。退出、换账号时不能继续展示上个人的信息。

## 5. 怎么知道做对了

用两个普通账号 A、B 和虚构资料验证：

1. A 保存自己的偏好和记忆；切换 B，不能加载或检索到 A 的内容。
2. A、B 分别保存不同内容；重新登录 A，仍能加载 A 自己的内容。
3. B 即使知道 A 的用户 ID、会话 ID，直接改请求参数，也不能读取或修改 A 的内容。检查实际检索结果/传给模型的上下文，不能只看最终回答碰巧没有提到。

三个步骤都要有测试结果。**加了 user_id 字段不等于完成隔离，读写都按它限定才算完成。**

本分支的认证与网页回归已有 31 项测试；它们不代表后续新写的 profile/记忆模块自动通过上述验收。

## 可直接交给其他同学 AI 的说明

```text
请为【我的模块名称和需求】接入当前仓库已有的用户登录。
先阅读 docs/AUTH-INTEGRATION.md、auth/dependencies.py、web/app.py，
确认认证分支代码已存在，不要重写登录或跳过鉴权。

本次目标很简单：不同用户加载和保存各自的 profile、记忆。
后端通过 Depends(require_user) 获取 user.id；读写都使用这个 ID，
不能信任前端或模型传来的 user_id。长期记忆沿用现有 memory_user_id，
短期上下文包含用户和会话 ID。不要用全局变量保存当前用户资料。
前端复用 MedixAuth.fetch，退出/切换账号时清空旧数据并重新加载。
数据库复用现有 Base 和 Alembic，不额外设计复杂权限系统。

完成后运行文档中的 A/B 双账号验收，提交改动说明和实际测试结果。
未验证的外部记忆服务请明确说明，不要声称已经验证隔离。
保留在自己的功能分支，交给组长和评审同学审核后再合并。
```

补充：原项目的医学知识库目前是共享的公共资料。本轮先完成个人 profile/记忆隔离；如果后续加入私人病历或私人知识库，负责人需要在文件、分块检索等读写路径另外接入用户归属检查，不能直接混入现有公共集合。

# 账号对接：所有私有数据使用同一个 user.id

当前网页账号使用手机号注册，支持手机号＋密码、手机号＋验证码登录；两种方式进入同一个账号。昵称仅供展示，修改手机号、密码或头像不会改变 `user.id`。

## 后端

```python
from fastapi import Depends
from auth.dependencies import require_user
from auth.schemas import CurrentUser

@router.get('/api/my-data')
def my_data(user: CurrentUser = Depends(require_user)):
    return store.load(owner=user.id)
```

- 保存、查询、修改、删除都用服务端取得的 `user.id`；不能信任前端或模型提供的 user_id。
- 按记录 ID 操作时，也检查 owner；知道别人的记录编号不等于拥有访问权限。
- 新表接入现有 Alembic 迁移链。业务库统一为 `MEDIX_DATABASE_URL`，默认 `.medix-data/app.db`。
- 普通业务使用 `require_user`；用户管理使用 `require_admin`。管理员不会自动获得所有人的医疗资料读取权限。

## 当前模块的身份约定

| 模块 | 使用方式 |
|---|---|
| 档案和回答偏好 | `user.id`，复用 personalization 的 Store/API |
| 病例和事实修订 | `web.case_memory`，owner=`user.id` |
| 本地健康记忆 | `memory.case_memory.CaseMemory`，owner=`user.id`，再区分本人/父亲/母亲 |
| 云端记忆 | `WebMem0Memory`，传原始 `user.id`，内部生成带环境和人物的命名空间；不要自行再拼一遍 |
| 网页短期上下文 | `web-{user.id}-{chat_id}` |
| 渠道短期上下文 | `web-{user.id}-wechat` 或 `web-{user.id}-qq` |
| 提醒和渠道绑定 | `reminders`、`messenger`，user_id=`user.id` |

云端记忆由网页统一处理；不要在 Agent 内另启一套未隔离的 Mem0，也不要把所有人的资料存在全局变量中。每台开发机设置不同且稳定的 `MEDIX_IDENTITY_NAMESPACE`，演示环境固定一个值。

公共医学知识库可以共享；病例、档案和记忆必须按账号限定。向量索引是检索存储，不再建一套登录账号。

## 前端

```javascript
if (!await MedixAuth.requireLogin()) return;
const response = await MedixAuth.fetch('/api/my-data');
// 写请求统一使用 JSON：
await MedixAuth.fetch('/api/my-data', {
  method:'POST', headers:{'Content-Type':'application/json'},
  body:JSON.stringify({content:'业务内容'})
});
```

退出登录监听 `medix-signout` 清空旧用户界面；`medix-auth-change` 后重新加载当前用户。不要在未登录的页面初始化时调用 requireLogin 强制弹窗。

## 交给其他同学 AI 的要求

> 阅读本文与 docs/INTEGRATION.md，复用已有鉴权和业务数据库。所有私有读写由 require_user 获得 user.id，并在每次查询中检查归属；不得让前端或模型指定身份。不要重写登录、复制账号表、创建另一份业务数据库。用两个合成账号验证 A 的资料在 B 下不能读取、修改、删除或进入模型上下文。运行 python scripts/verify_integration.py。

注销账号清理本地有外键关联的数据；远程 Mem0 的物理清除不在本轮本地集成验收范围，新注册账号不会复用已注销账号的身份。

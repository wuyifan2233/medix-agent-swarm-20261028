# 个性化接口文档 v4：注册基本信息

更新日期：2026-10-31；分支 `feature/health-profile-evolution`。

## 注册

`POST /api/auth/register` 沿用用户名与密码认证，必须传入 `basic_profile` 对象：

```json
{"username":"example_user","password":"由用户自行设置","basic_profile":{"name":"示例姓名","birth_month":"1995-06","sex":"female"}}
```

- `birth_month`：null 或 `YYYY-MM` 字符串，只记录出生年月，不含出生日。不能晚于当前月份，不能早于当前月份前130年。
- `sex`：`female`、`male` 或 `undisclosed`（默认）。
- 三项均可不提供，空表单仍提交对象；不要求勾选确认。未知值不推断。
- 年龄、身高、体重及病史、用药等额外字段均返回422；缺少对象同样返回422。
- 成功201，重复账号409。账号和基本信息同事务创建，失败整体回滚；注册接口不调用模型。

## 只读查看

`GET /api/profile` 需要登录，仅返回当前账号记录。包含 `data`、`revision`、`confirmed_at`、`updated_at`、`usable`、`status`、`read_only`。

`data` 仅含 `name`、`birth_month`、`sex`。有记录时版本1、只读true、状态 `registration_record`，时间戳为注册记录时间。无记录时版本0、usable=false、状态 `not_recorded`。

已有记录中的年龄、身高和体重不再展示或注入问答；不从旧年龄反推出生年月。不迁入旧病史，不提供登录后补填。

## 问答默认参考

`POST /api/chat` 默认 `use_profile=true`、`profile_revision=1`、`profile_fields=["name","birth_month","sex"]`。页面不显示逐轮开关或字段选择。

接口兼容显式 `use_profile=false` 和字段裁剪；范围非空且无重复，只接受三项基本信息字段，非法范围返回400。存在记录时版本不匹配返回409，无记录时正常回答，不注入档案。

后台按登录账号重新读取记录，裁剪后用于检索和上下文。标记注册时间及当前日期，可按出生年月估算年龄，但没有出生日，不能声称知道确切生日或精确日龄。询问他人、假设场景时不得套用本人信息。

问答不主动追问、重复确认或索要授权；缺失信息说明判断范围及适用条件，保留必要风险提示。本轮描述只参与回答，不写回档案。

响应保留 `profile_used`、`profile_revision`、`profile_fields`、`profile_confirmed_at`，没有档案写入卡片。

## 回答偏好与旧接口

`GET/PUT /api/profile/reply-preferences` 独立保存称呼、语气、详略和表达设置，需要启用并保存，不修改基本信息。`reply_preferences_status` 为 off/applied/fallback，整理失败保留原回答。统一 `answer_policy` 约束生成及表达整理。

旧编辑、确认、恢复、病历提取、聊天候选及采纳接口不再挂载，返回404或405。旧数据保留，不用于当前问答。

使用基本信息或启用偏好时暂停本轮云端记忆；上下文按账号、使用范围和偏好版本隔离。私有读取依据会话；写请求沿用可信Origin、JSON、自定义请求头与CSRF校验，公开注册沿用原认证规则。

## 数据兼容

`registration_profiles` 表由迁移 `20261031_05` 建立，一账号一条注册记录。此次字段调整不新增数据库迁移，通过输入校验及读取字段过滤生效，不删除历史原始数据。

注册后没有基本信息更新、删除或恢复接口。401未登录，403来源或CSRF失败，409冲突，422字段非法。

## 姓名与账号持久保存

`name` 为可选姓名，最多50字符，去除首尾空格，空值保存null，拒绝控制字符。姓名随出生年月、性别在注册事务中写入registration_profiles，以服务端user_id为唯一主键绑定账号；退出、重新登录及服务重启后按同一账号读取，不依赖浏览器临时缓存，也不接受客户端指定其他档案所有者。旧账号姓名缺失时显示未提供，不推断、不自动补录。

姓名用于只读展示及自然称呼；已设置回答偏好称呼时优先偏好。姓名不参与医学检索，也不用于推断身体状况。新增双账号、重新登录、重新建立数据库连接及伪造user_id查询的持久保存与隔离验证。

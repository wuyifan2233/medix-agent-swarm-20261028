# 个性化接口文档 v4：注册基本信息

更新日期：2026-10-31；分支 `feature/health-profile-evolution`。

## 注册

`POST /api/auth/phone/register` 使用手机号短信注册，必须传入 `basic_profile` 对象（旧用户名注册仅用于显式启用的兼容测试）：

```json
{"challenge_id":"短信挑战ID","code":"短信验证码","new_password":"由用户自行设置","basic_profile":{"name":"示例姓名","birth_month":"1995-06","sex":"female"}}
```

- `birth_month`：null 或 `YYYY-MM` 字符串，只记录出生年月，不含出生日。不能晚于当前月份，不能早于当前月份前130年。
- `sex`：`female`、`male` 或 `undisclosed`（默认）。
- 三项均可不提供，空表单仍提交对象；不要求勾选确认。未知值不推断。
- 年龄、身高、体重及病史、用药等额外字段均返回422；缺少对象同样返回422。
- 手机号注册成功200并自动登录；重复账号按现有短信认证流程拒绝。账号和基本信息同事务创建，失败整体回滚；注册接口不调用模型。

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

`GET/PUT /api/profile/reply-preferences` 独立保存称呼、语气、详略和表达设置，需要启用并保存，不修改基本信息。`reply_preferences_status` 为 off/applied/fallback，整理失败保留原回答。生成及表达整理保留 main_copy 的策略和语音设置。

旧编辑、确认、恢复、病历提取、聊天候选及采纳接口不再挂载，返回404或405。旧数据保留，不用于当前问答。

使用基本信息或启用偏好时暂停本轮云端记忆；上下文按账号、使用范围和偏好版本隔离。私有读取依据会话；写请求沿用可信Origin、JSON、自定义请求头与CSRF校验，公开注册沿用原认证规则。

## 数据兼容

`registration_profiles` 表由迁移 `20261031_18` 建立，一账号一条注册记录。此次字段调整不新增数据库迁移，通过输入校验及读取字段过滤生效，不删除历史原始数据。

```json
{"expected_revision":0,"data":{"enabled":true,"nickname":"小王","tone":"supportive","voice_profile":"auto","detail":"brief","format":"summary_first","terminology":"plain","communication_note":"先说重点","daily_context":"希望建议拆成小步骤"}}
```

| 字段 | 值/限制 |
| --- | --- |
| enabled | 严格布尔，默认false；**已保存不等于已启用** |
| nickname | 最多20字，可空 |
| tone | neutral / supportive / direct |
| voice_profile | auto / gentle / clear / steady，默认auto；关闭enabled时不应用 |
| detail | brief / standard / detailed |
| format | summary_first / steps / explanation |
| terminology | plain / professional |
| communication_note / daily_context | 各最多200字，仅作表达与日常安排偏好，不是健康事实 |

必须勾选启用并保存；下一次新提问生效，旧回答不改写。本轮明确要求优先。
语音包随账号偏好保存；auto按tone映射为supportive→gentle（柔和女声、节奏稍慢）、direct→clear（明亮男声、节奏自然）、neutral→steady（平和女声、清晰舒缓）。固定选择覆盖语气映射。启用并保存后从下次播报生效；关闭enabled则使用服务默认声音，不自动推断健康档案。试听未保存选项不改变偏好版本，也不调用文字模型。详见[语音实现说明](VOICE.md#个性化语音包2026-10-31)。

恢复默认通过保存默认值、清空文本并关闭enabled实现，版本继续递增。偏好独立于健康档案，不改变档案确认状态。
最终呈现增加一次模型调用，要求保留关键风险、就医提示和不确定性，不能机械截断；简短目标120–220字，详细在问题需要时目标700–1000字，不是精确字数保证。
整理失败或输出截断时保留完整原回答并明确提示，不能声称已完整应用。

姓名用于只读展示及自然称呼；已设置回答偏好称呼时优先偏好。姓名不参与医学检索，也不用于推断身体状况。新增双账号、重新登录、重新建立数据库连接及伪造user_id查询的持久保存与隔离验证。

## 回答偏好单次保存

偏好界面不再提供启用勾选，点击“保存回答偏好”时直接提交enabled=true，一次保存即可在下次提问中生效；恢复默认按钮仍可关闭偏好。删除底部常驻说明与版本提示，仅保留简短保存结果或错误反馈。已有回答不自动改写，后端偏好接口及风险提示约束保持不变。

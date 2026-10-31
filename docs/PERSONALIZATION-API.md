# 个性化功能接口文档 v3

更新日期：2026-10-30。对应分支：`feature/health-profile-evolution`。
基础地址：`http://127.0.0.1:8765`。本文按当前实现整理；文档v3不改变导出接口的`schema_version: 2`。

## 共同约定

- 复用现有认证系统；用户身份来自服务端登录会话，不接受客户端user_id或完整档案快照。
- 写请求需要可信Origin、JSON Content-Type、`X-Medix-Request: 1`、会话Cookie及`X-CSRF-Token`。网页统一使用`MedixAuth.fetch`。
- 结构化请求禁止额外字段；版本为整数，日期为YYYY-MM-DD，时间戳为Unix秒。
- `expected_revision`是读取时的当前版本。冲突返回409，应重新读取并核对，不盲目重试覆盖。
- 档案使用授权、发送模型提取授权、逐项采纳、主动确认和回答偏好启用彼此独立。

## 档案数据

`ProfileData`包含七类可授权字段：`age / sex / conditions / allergies / medications / symptoms / followups`，以及`field_sources`。

| 字段 | 约束与含义 |
| --- | --- |
| age | null或0–130整数，记录时年龄，不自动增长 |
| sex | unknown / female / male / other / undisclosed |
| conditions | 基础病史；对话提取仅接受明确自述获诊断的内容 |
| allergies / medications / symptoms | 过敏、用药、症状与近期身体状况 |
| followups | 建议与待核实事项，不是病情事实、已执行检查或当前用药 |
| field_sources | 仅age、sex的来源 |

五个列表字段均为`{status, items}`。组status为unknown、none_reported或reported；reported必须有条目，其余必须为空，每组最多20项。
条目包含`name`(1–80字)、`note`(最多160字)、`status`、`source`；药物还可含`dose/frequency`(各最多60字)。
条目status为reported、historical、unknown、current或stopped；它们表示记录性质，不能验证实时病情。
followups里的current仅表示用户选择跟进中，不代表已经执行建议。

来源为null或`{kind,label,report_date,excerpt}`：kind为manual/report/conversation/assistant，label最多100字，excerpt最多240字。
来源记录不等于真实性认证；旧档案缺失symptoms、followups时默认补为未知空列表。

## 档案、版本和确认

| 方法与路径 | 请求 | 返回/行为 |
| --- | --- | --- |
| GET `/api/profile` | 无 | `{data,revision,updated_at,confirmed_at,status,usable}`，首次revision=0 |
| PUT `/api/profile` | `{expected_revision,data}` | 新版本待确认草稿 |
| POST `/api/profile/confirm` | `{expected_revision,acknowledged:true}` | 主动确认已保存版本 |
| DELETE `/api/profile` | `{expected_revision}` | 清空档案、历史及待采纳候选；不可恢复 |
| GET `/api/profile/history` | 无 | `{items:[...]}`，仅当前账号历史 |
| POST `/api/profile/restore` | `{expected_revision,target_revision}` | 恢复为新草稿，不继承旧确认 |
| GET `/api/profile/export` | 无 | `{schema_version:2,profile:{...}}`，仅当前档案 |

档案状态为empty、draft、confirmed或review_required；确认超过90天需重新核对。这是产品复核周期，不是临床有效期。
保存、采纳或恢复都会使档案重新待确认。

## 病历提取候选

`POST /api/profile/imports`，成功201：

```json
{"text":"虚构病历文字","images":[],"label":"测试病历","report_date":"2020-01-01","subject":"self","consent_to_model":true,"expected_revision":3}
```

text最多12000字；images最多3张，为图片data URL字符串。文字和图片至少提供一种；日期不得晚于今天。
支持PNG/JPEG/WebP，经过格式、大小、像素校验和元数据处理；不支持直接解析PDF或Word。
只生成带证据的临时候选，不写入档案；旧病历条目为historical或unknown，不自动视为当前正在用药。

## 对话与回答候选

`POST /api/profile/conversation-candidates`，成功201：

```json
{"text":"我这两天头痛","subject":"self","consent_to_model":true,"expected_revision":3,"job_id":"本轮已完成任务ID，可省略"}
```

- text为用户本轮原话，1–8000字；subject必须self且主动授权。
- 不传job_id：仅整理本人原话；他人、假设、否定和纯问题不作为本人事实，归属不明或推断疾病转为澄清。
- 传job_id：服务器读取本账号已完成且原问题与text一致的回答，客户端不能提交任意助手回答替代。
- 助手回答只可产生followups候选，保留助手原文和assistant来源，强制uncertain=true、status=unknown，不补写用户诊断或药物事实。
- job不存在或不属于当前账号返回404，未完成或原问题不匹配返回409。服务重启或任务过期后需重新提问。
- 对话自述来源日期是整理日期，发病时间保留在原话/说明中；系统不能核验病情真伪。

两类提取响应共有：`id,base_revision,current_revision,expires_at,consumed,candidates`。
每项候选包含`id,field,value,evidence,uncertain,source,existing`；对话接口额外返回`clarifications,notice`。
候选有效期1小时，每账号最多10个未消费批次。

## 逐项采纳和替换规则

| 方法与路径 | 行为 |
| --- | --- |
| GET `/api/profile/imports/{id}` | 读取本账号候选和当前字段对照 |
| DELETE `/api/profile/imports/{id}` | 丢弃候选，成功204，不修改档案 |
| POST `/api/profile/imports/{id}/apply` | 原子采纳所选项，成功返回新档案草稿 |

```json
{"expected_revision":3,"selections":[{"candidate_id":"候选ID","action":"append","target_index":null,"acknowledge_uncertainty":false}]}
```

- 单次1–30个选择。未选内容不会保存；不确定项必须单独将acknowledge_uncertainty设为true。
- 年龄、性别只允许replace，target_index为null。
- 列表追加使用append；更新同名旧项使用replace并指定原列表的target_index。
- **不同名称不能替换**：“感冒”不能覆盖“头痛”。名称比较采用NFKC规范化、去空白、转小写；不做近义词或疾病关联推断。
- 同名重复追加返回422，需明确更新同名项或不采纳。不能重复选择候选、重复替换同一下标、替换本次刚追加的项。
- 跨名称替换返回422；事务回滚，原档案不变，候选不被消费，可改选追加。

前端：只有一个操作时隐藏下拉框，以文字说明“采纳后追加保存，保留已有记录”；年龄、性别提示将更新该字段。
从自述无记录转为有记录时另行说明。存在多个操作时才显示选择框；不会默认替用户选择覆盖旧记录。
这是界面呈现优化，apply请求结构没有改变。

## 问答中使用档案

`POST /api/chat`，成功202返回`job_id`；`GET /api/jobs/{job_id}`读取本账号进度与结果。

```json
{"message":"请分析本次问题","images":[],"chat_id":"有效UUID","remember":false,"use_profile":true,"profile_revision":4,"profile_fields":["conditions","allergies"]}
```

use_profile默认false。开启时需有效已确认版本；profile_fields省略时为全部七类，显式提供时必须非空且不重复。
未授权字段不会进入检索、档案上下文；口头同意不能代替页面开关。图片聊天images采用`web/app.py`的图片对象格式，与病历提取的字符串数组不同。
结果包含`profile_used/profile_revision/profile_fields/profile_confirmed_at/memory_suppressed_for_profile`。
相关档案需与具体建议对应；旧症状、已停药和待核实建议不能作为当前事实，无关档案不强行影响回答。

## 回答偏好

GET `/api/profile/reply-preferences`返回`{data,revision,updated_at}`；PUT同路径提交`{expected_revision,data}`。

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

聊天结果额外包含`reply_preferences_used/reply_preferences_revision/reply_preferences_status/reply_preferences_detail/memory_suppressed_for_preferences`。
status为off、applied或fallback；used表示启用了偏好流程，不等于整理一定成功。
启用档案或偏好时暂停本轮Mem0写入；切换授权范围或偏好版本时隔离旧对话上下文。

## 错误处理与页面入口

| 状态码 | 常见含义 |
| --- | --- |
| 400 | 聊天参数或字段范围错误 |
| 401 / 403 | 未登录 / CSRF或来源校验失败 |
| 404 | 当前账号无权访问的候选、任务或版本 |
| 409 | 版本冲突、草稿不可用于问答、任务不匹配 |
| 410 | 提取候选过期 |
| 413 / 422 | 内容过大 / 字段、选择或替换规则不合法 |
| 429 | 未处理候选或排队任务过多 |
| 502 / 503 / 504 | 提取失败 / 模型未配置 / 超时 |

回答末尾提供“把有用的信息留在健康档案”操作区，点击“选择加入健康档案”展开选择面板。
档案引用、字段和偏好版本默认收在“查看说明”；偏好整理失败时说明展开。
“同时参考本轮回答”默认关闭，所有候选默认不选；不自动提取、不自动采纳、不自动确认。

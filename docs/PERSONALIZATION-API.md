# 个性化档案接口文档 v2

## 对话更新扩展（2026-10-30）

新增 `POST /api/profile/conversation-candidates`：

```json
{"text":"我这两天头痛", "subject":"self", "consent_to_model":true, "expected_revision":3}
```

需登录和CSRF，text最多8000字符。它只生成候选，不直接保存档案。
响应兼容病历候选的id/base_revision/candidates，另有clarifications（需用户澄清的问题）和notice。
候选仍通过 `/api/profile/imports/{id}/apply` 逐项采纳，再通过 `/api/profile/confirm` 主动确认。
它并非核验病情真伪：source.kind=conversation，来源标签固定为“本人对话自述（未经医学核实）”。
source.report_date在此表示整理自述的日期，原话中发病时间保留在note，不根据日期推算病情。

新增ProfileData.symptoms，与conditions等列表同构，用于症状与近期身体状况，不等同于确诊病史。
profile_fields现在也允许symptoms；省略字段范围时兼容读取全部六类字段。
source.kind增加conversation。旧档案缺少symptoms时按未知空列表读取，无须数据库迁移。

每个事实分别研判归属与语气：他人、假设、否定和纯提问不进入候选；归属不明、推断疾病需澄清。
疑似的本人描述保留不确定标记，采纳时必须单独确认，并以unknown保存。
只有明确自述确诊/医生诊断的内容才能提出conditions候选，仍不代表系统验证过该诊断。
仅使用用户原话，不从助手回答或公共检索片段提取个人事实；证据不是原话子串时拒绝。

网页每次回答旁提供“筛选本轮内容，选择加入健康档案”。点击后在回答下方展开选择面板，用户确认本人实际经历和模型筛选授权后提取。候选默认全部不加入，逐项勾选并明确追加或替换后才保存；“暂不加入”会丢弃候选，不修改档案。
普通问答默认不自动提取或写档案，关闭“参考档案”开关也不等于同意更新档案，两种授权独立。

适用本地分支：`health-profile-evolution`。基于 `167ec3f`，新增代码未推送远程。
基础地址：`http://127.0.0.1:8765`。日期采用 `YYYY-MM-DD`；时间戳采用 Unix 秒。

## 身份、安全与共同约定

复用认证分支的 `MedixAuth` 与 `Depends(require_user)`。业务接口不接收用户ID。
所有读写按服务端当前账号 `user.id` 限定，不能通过候选ID、版本号访问其他账号。

浏览器调用示例：

```javascript
if (!await MedixAuth.requireLogin()) return;
const response = await MedixAuth.fetch('/api/profile');
if (!response.ok) throw new Error(await MedixAuth.detail(response));
const profile = await response.json();
```

写入示例：

```javascript
await MedixAuth.fetch('/api/profile/confirm', {
  method: 'POST',
  body: JSON.stringify({expected_revision: 2, acknowledged: true})
});
```

`MedixAuth.fetch` 负责会话 Cookie、JSON Content-Type、CSRF 与 `X-Medix-Request: 1`。
直接调用HTTP时需要同源 Origin、登录会话 Cookie、`X-CSRF-Token` 和上述头部；不要把这些凭证提交到Git。
所有对象禁止额外字段。错误响应不回显病历与档案原文。

## 数据模型

```json
{
  "age": 35,
  "sex": "female",
  "field_sources": {
    "age": {"kind":"report", "label":"虚构病历", "report_date":"2020-01-01", "excerpt":"年龄35岁"}
  },
  "conditions": {"status":"reported", "items":[
    {"name":"虚构病史", "note":"仅用于测试", "status":"historical", "source":{
      "kind":"report", "label":"虚构病历", "report_date":"2020-01-01", "excerpt":"既往虚构病史"
    }}
  ]},
  "allergies": {"status":"unknown", "items":[]},
  "medications": {"status":"reported", "items":[
    {"name":"测试药甲", "note":"旧病历记录", "status":"historical", "dose":"原文剂量", "frequency":"每日一次", "source":null}
  ]}
}
```

| 字段 | 类型与含义 |
| --- | --- |
| age | 0–130整数或null，不自动根据时间增长；来源日期决定记录时点 |
| sex | unknown / female / male / other / undisclosed |
| conditions / allergies / medications | 包含组状态status与items |
| 组status | unknown=未知；none_reported=本人自述无记录；reported=有条目 |
| 条目status | reported=曾报告；historical=历史；unknown=不确定；current=本人在确认时自述当前存在或使用；stopped=自述已停用 |
| source | 可为null，或kind、label、report_date、excerpt；仅记录资料来源，不代表医疗机构验证 |
| field_sources | 仅允许age与sex的来源 |

每组最多20条；name最多80字，note最多160字，dose/frequency各60字。
source.label最多100字、excerpt最多240字。组状态reported必须有条目，其他组状态必须为空。
current不代表实时验证；旧病历模型提取结果只能为historical或unknown，不能自动认定现用。

## 档案读取、编辑、确认、清空

| 方法与路径 | 请求 | 返回 |
| --- | --- | --- |
| GET `/api/profile` | 无 | 当前档案，未建档时revision=0 |
| PUT `/api/profile` | `{expected_revision, data}` | 新版本待确认草稿 |
| POST `/api/profile/confirm` | `{expected_revision, acknowledged:true}` | 确认当前版本 |
| DELETE `/api/profile` | `{expected_revision}` | 新版本空白草稿；清除历史内容和所有待采纳候选 |

档案响应结构：

```json
{"data":{}, "revision":2, "updated_at":1793260800, "confirmed_at":null, "status":"draft", "usable":false}
```

data实际为完整ProfileData。status为empty/draft/confirmed/review_required。
确认超过90天需复核，这是产品复核间隔，不代表医学有效期。
编辑、采纳、恢复、清空都会增加revision并撤销确认。并发写入通过expected_revision进行乐观锁检查。
清空后只保留不含健康内容的空白版本，不能再恢复之前的数据；不删除其他模块的聊天和云端记忆。

## 病历提取

### POST `/api/profile/imports`

输入JSON，文字或图片至少提供一种：

```json
{
  "expected_revision":2,
  "label":"虚构门诊记录",
  "report_date":"2020-01-01",
  "subject":"self",
  "consent_to_model":true,
  "text":"虚构病历原文……",
  "images":[]
}
```

text最多12000字符；images最多3个PNG/JPEG/WebP的base64 data URL，每张原始图片不超过8MB、2000万像素。
整个提取请求最多34MB；其他档案写请求最多64KB。
subject只允许self，consent_to_model必须为布尔true；日期必填且不晚于今天。
图片先校验、去元数据、压缩和转录，再与文字一起提取候选；不保存原始图片。
如果模型不支持图像输入，返回提取失败，用户可改为粘贴文字。

成功返回201：

```json
{
  "id":"服务端生成的UUID",
  "base_revision":2,
  "current_revision":2,
  "expires_at":1793264400,
  "consumed":false,
  "candidates":[{
    "id":"候选UUID", "field":"conditions",
    "value":{"name":"测试病史", "note":"旧记录", "status":"historical", "source":null},
    "evidence":"原文中的逐字片段", "uncertain":false,
    "source":{"kind":"report", "label":"虚构门诊记录", "report_date":"2020-01-01", "excerpt":"原文中的逐字片段"},
    "existing":{"status":"unknown", "items":[]}
  }]
}
```

field支持age/sex/conditions/allergies/medications。age的value为整数，sex为枚举字符串；其余为条目对象。
existing为当前档案对应字段，供页面并排比较。模型最多返回30个候选，证据必须与上传文字或图片转录文字匹配。
疑似、待排、模糊文字等候选需要标记不确定；证据匹配不代表OCR或医学判断一定正确，用户仍须核对。
提取本身不修改档案。候选有效期1小时，每账号最多10份未消费草稿。

### GET `/api/profile/imports/{id}`

返回本账号候选与当前字段的对照。过期返回410，他人或不存在的ID返回404。
档案被其他窗口编辑后current_revision可能不同，采纳时会返回409，需重新提取。

### POST `/api/profile/imports/{id}/apply`

```json
{
  "expected_revision":2,
  "selections":[
    {"candidate_id":"候选UUID", "action":"append", "target_index":null, "acknowledge_uncertainty":false},
    {"candidate_id":"另一候选UUID", "action":"replace", "target_index":0, "acknowledge_uncertainty":true}
  ]
}
```

至少选1项。age/sex仅允许replace且target_index=null，每个基础字段一次只能选一个值。
列表append保留旧项；已有同名条目时必须明确replace；replace需要指定原列表下标。
同一旧条目不能重复替换，不能指定本次刚追加条目的下标。未选候选不进入档案。
不确定候选必须单独acknowledge_uncertainty=true，采纳后仍为unknown，不会升级为确诊。
成功返回200与新版档案。候选消费、档案更新和历史版本写入在同一事务中完成。
此结果仍是draft，用户必须在档案页再次确认，不能直接进入RAG。整批候选不可重复消费。

### DELETE `/api/profile/imports/{id}`

带JSON空对象 `{}`；成功204。可丢弃过期候选，不修改档案。

## 历史、恢复、导出

| 方法与路径 | 说明 |
| --- | --- |
| GET `/api/profile/history` | `{items:[{revision,data,saved_at,confirmed_at,action}]}`，当前账号最近50版，倒序 |
| POST `/api/profile/restore` | `{expected_revision,target_revision}`；恢复本账号旧版为新草稿，不自动确认 |
| GET `/api/profile/export` | `{schema_version:2,profile:{...}}`，当前档案JSON；浏览器保存为文件 |

action可能为baseline/edit/report_import/restore/clear。确认状态记录在对应版本，不改变版本号。
历史表保留每次保存的快照；升级时回填升级前当前档案为baseline，不虚构更早历史。
导出含健康数据，需由用户妥善保存，不含认证凭证。

## 聊天授权扩展

在现有POST `/api/chat`中可增加：

```json
{"use_profile":true, "profile_revision":3, "profile_fields":["allergies","medications"]}
```

完整请求仍需message、chat_id、images、remember等原字段。
profile_fields只允许五个档案字段，至少1个、不能重复；未传时为五个字段（兼容旧客户端）。
未授权字段会在服务端裁剪，来源信息也一并裁剪。字段范围改变会重置底层历史上下文。
use_profile为false或不传时不读取档案，口头同意不替代页面开关。
任务结果增加profile_used/profile_revision/profile_confirmed_at/profile_fields，供页面展示实际使用范围。
包含档案的轮次暂停Mem0读写，防止另存未受确认状态控制的副本。

## 错误码

| 状态码 | 含义与客户端处理 |
| --- | --- |
| 401 | 未登录或会话失效，重新登录 |
| 403 | Origin、CSRF或请求格式检查失败 |
| 404 | 本账号下资源不存在，不区分是否属于别人 |
| 409 | 档案版本变化、候选已消费；刷新核对或重新提取 |
| 410 | 候选过期，重新提取 |
| 413 | 请求体超过限制 |
| 422 | 字段、选择、确认或数量验证不通过 |
| 429 | 待处理候选达到账号上限，先丢弃或采纳 |
| 502 | 模型格式、证据或图片能力等提取失败；可用文字或手填 |
| 503 | 模型Key未配置 |
| 504 | 提取超过125秒 |


## 结合本轮回答追加待核实事项

POST /api/profile/conversation-candidates 新增可选 job_id：不传时只整理用户原话；传入时读取本账号已完成且 request_text 与 text 一致的回答。
找不到或不属于本账号返回404，未完成或原话不匹配返回409；任务过期或服务重启后需重新提问。
前端“同时参考本轮回答”默认关闭，用户主动授权后才发送所选回答给模型。
新增 profile.data.followups（status/items结构）和可授权字段 followups，旧档案自动补为空，无需数据库列迁移。
助手回答只可生成 followups 候选，来源 kind=assistant，保留回答原文证据；不能补全用户事实、诊断或当前药物。
候选强制 uncertain=true/status=unknown，必须逐项勾选并额外确认后才能采纳，仍需重新确认整份档案。
档案新增“建议与待核实事项（非病情事实）”分区。后续问答仅把它当待核实建议，不作为病史或已执行事项；公共知识检索不把建议当作症状关键词。
测试：本人描述“我这两天头痛”，本轮回答含观察或就医建议，选择参考回答→筛选→仅选建议→额外核对→保存；检查仅followups变化且档案为草稿。
同时验证关闭参考回答不生成助手建议、他人任务404、不匹配原话409、未额外确认422、未选候选不保存。


## 回答偏好（与健康档案独立）

GET /api/profile/reply-preferences 返回 {data, revision, updated_at}；首次默认enabled=false。
PUT 同路径，提交 {expected_revision, data}，需要登录、可信Origin及CSRF；版本冲突409、非法字段422。
data字段：enabled(bool)、nickname(最多20字)、tone(neutral/supportive/direct)、detail(brief/standard/detailed)、
format(summary_first/steps/explanation)、terminology(plain/professional)、communication_note及daily_context(各最多200字)。
用户身份只来自服务端会话；不同账号互不可见。恢复默认通过PUT保存默认值、清空文本并关闭enabled，版本继续递增。
使用独立reply_preferences表，迁移20261030_04；旧用户默认为关闭，不改变健康档案或其确认状态。
后端分析时读取当前账号偏好，只影响表达与执行建议的安排，不用于医学知识检索，不作为病史，不能绕过档案开关。
自由文本作为低优先级数据处理，本轮明确要求和必要风险提示优先；不提供真人医生角色或诊断身份设定。
启用时暂停云端记忆，避免将称呼、日常安排等随增强提示保存到Mem0；修改或关闭偏好时隔离旧上下文。
任务结果新增reply_preferences_used、reply_preferences_revision和memory_suppressed_for_preferences；不返回偏好文本。
前端入口“回答偏好”，默认不开启，显式保存后下次提问生效。设置页面不在localStorage保存文本；切换账号会清理弹窗。
验收：分别设置“简短重点＋分步骤”和“详细说明＋解释原因”，同一问题比较；再关闭偏好、换账号和关闭档案验证隔离。
自动化覆盖持久化、版本冲突、身份/CSRF、字段校验、真实提示注入链路、检索排除、档案不写入和关闭后历史隔离；实际模型风格需单独验收。


## 回答偏好最终呈现修复

偏好必须启用并保存，对下一次新提问生效，不会改写已有回答。固定咨询助手模板可能弱化增强提示中的偏好，
因此在所有助手完成后增加独立最终呈现步骤，使用系统级表达要求重新组织原答复，昵称有显式兜底。
简短目标120—220字（必要风险可能超出），详细在问题需要时目标700—1000字；不能为凑长度添加医学事实。
本轮明确要求优先，不能删去关键风险、就医提示、用药限制或不确定性；不机械截断文本。
该步骤增加一次模型调用（最大约38秒），失败或输出截断则保留完整原答复并显示偏好整理失败，不能声称已完整应用。
结果新增reply_preferences_status=off/applied/fallback，以及reply_preferences_detail；前端显示版本和所选详略。
模型排版不能保证逐字数精确或完全语义等价，仍需真实对照验收，尤其关注简短模式是否保留必要风险。


## 防止无关条目覆盖

列表型档案候选仅允许更新同名记录（名称做NFKC、去空白、转小写规范化）；不同症状/疾病默认追加。
如“感冒”与现有“头痛”互不替代。前端只列同名更新选项，后端对跨名称替换返回422且不消费候选。
同名重复追加同样返回422，需明确选择更新同名项；昵称别名、近义疾病不自动归并，可在档案中人工核对整理。
年龄、性别仍为基础字段明确替换，不受列表规则影响；该规则同时覆盖对话候选和病历导入。

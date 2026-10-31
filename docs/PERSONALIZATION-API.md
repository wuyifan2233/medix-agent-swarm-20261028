# 个性化接口文档 v4：注册基本信息

更新日期：2026-10-31；分支feature/health-profile-evolution。本版以注册时一次填写、默认参考、后续只读的身体基本信息替代病情档案演进流程。

## 注册

POST /api/auth/register，保持原用户名与密码认证，新增必填basic_profile对象：

```json
{"username":"example_user","password":"由用户自行设置","basic_profile":{"age":30,"sex":"undisclosed","height_cm":165,"weight_kg":55}}
```

- age：null或0–130整数；sex：female/male/undisclosed；height_cm：null或30–250数字；weight_kg：null或1–400数字。
- 可全部不提供，仍需传入basic_profile对象，不再要求勾选确认。空输入对应null，不推断缺失值。
- 不收集疾病、过敏、用药或近期症状；额外字段、无basic_profile返回422。
- 注册201后保持原流程，用户再登录。重复用户名409。账号与基本信息在同一事务创建，失败整体回滚。
- 本接口不会将基本信息发送给模型。

## 查看基本信息

GET /api/profile，需要登录，只读取服务端当前账号。返回data、revision、confirmed_at、updated_at、usable、status、read_only。
data仅含age/sex/height_cm/weight_kg。新注册信息revision=1、read_only=true、status=registration_record，时间戳表示注册时记录时间。
旧账号未记录时revision=0、usable=false、status=not_recorded；不自动迁入旧病史，不提供登录后补填接口。

## 不再开放的接口

本版不挂载旧档案编辑、确认、清空、历史恢复/导出、病历提取、对话候选及采纳接口。
PUT/DELETE /api/profile以及旧/profile/confirm、/profile/restore、/profile/imports、/profile/conversation-candidates等返回404或405。
旧数据库数据保留，不显示为注册基本信息，不注入当前问答；后续不能通过旧接口更新。

## 问答授权

POST /api/chat继续支持use_profile、profile_revision、profile_fields。默认use_profile=false。
仅允许age、sex、height_cm、weight_kg四类，省略范围表示全部四类；显式范围必须非空且无重复。
使用时要求当前账号存在注册记录且profile_revision=1，缺失或错误版本409。旧病情字段返回400。
后台重新验证注册记录，按授权字段裁剪后参与检索和模型上下文。基本信息标明注册日期，不是当前测量，不自动增长年龄或更新体重。
本轮健康描述可以回答，但不能写回基本信息。未知字段不能推断病情，涉及当前数值需要询问本轮信息。
响应保留profile_used、profile_revision、profile_fields、profile_confirmed_at；不再提供对话写入操作卡片。

## 回答偏好与安全

GET/PUT /api/profile/reply-preferences保持v3实现：独立保存称呼、语气、详略和表达设置，不修改身体基本信息。
需显式启用并保存。结果reply_preferences_status为off/applied/fallback，整理失败保留完整原回答。
本人档案授权与回答偏好独立。使用基本信息或启用偏好时暂停本轮云端记忆，按账号、授权范围及偏好版本隔离上下文。
所有私有读取依据登录会话。写请求继续要求可信Origin、JSON、X-Medix-Request及CSRF（注册沿用原公开注册规则）。
401表示未登录，403表示来源/CSRF失败，409表示冲突，422表示注册或偏好字段非法。

## 数据与兼容

新增独立registration_profiles表，迁移20261031_05，仅添加表，不修改或删除旧档案及其历史。
本版没有身体基本信息编辑、删除或恢复接口。需修改历史错误信息时应另行定义维护/隐私流程，不能靠问答自动改写。
这次属于产品流程与接口契约变更，旧档案演进测试和调用方需要迁移，不能继续按v3写入接口使用。


## 默认参考更新

注册表单已删除核对确认勾选及“不询问疾病或用药”文案；basic_profile不再接收acknowledged。
已填写的注册基本信息默认用于个性化回答，页面不再提供逐轮开关或字段选择。POST /api/chat省略use_profile时默认为true，profile_revision默认1，profile_fields默认为四项。
旧账号无注册记录时正常回答且不注入档案。接口兼容显式use_profile=false或字段裁剪；本轮明确询问他人或假设情况时，不得将本人背景套用其中。
注册信息保持只读，回答偏好仍需要独立保存和启用。本节取代前文逐轮授权、主动确认相关描述。

问答行为补充：默认直接参考当前账号已有注册基本信息，不询问是否授权或要求开启档案。旧账号无记录时按未知回答，不要求返回注册补填；不主动追问或要求补充情况。


## 直接回答与档案冻结

问答不主动追问、索取补充资料或重复确认；资料不足时说明未知项、判断范围和适用条件，不猜测缺失信息。必要风险及紧急就医提示保留。
统一answer_policy约束同时用于问答上下文、请求内Worker系统提示及最终表达整理，防止偏好整理重新添加追问。
本轮自述只参与回答，不新增、补全或更新注册档案，不声称已记录；注册后只读接口约束保持生效。
用户明确要求生成问卷或题目属于完成用户任务，不视为主动追问。模型行为仍需实际验收，自动测试验证约束传递及写入接口隔离。

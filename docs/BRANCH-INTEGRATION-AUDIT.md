# main_copy 完整分支补合核对

本轮补入知识库 1f8c777 与提醒/机器人 2a3b6c8。完整合并指保留两个分支的真实 Git 合并关系，并核对全部功能变更；冲突处按统一身份、数据库和启动方案适配，不等于用旧文件覆盖新实现。

## 提醒分支全部40个变更文件

对照源：`git diff b0dcf55 2a3b6c8 --name-only`。除表中说明的适配外，其余函数接口和业务模块均保留。AST 核对只有旧 channel_path 与 local_session 两个顶层函数被统一存储/认证替代，没有缺少原分支的提醒或渠道业务方法。

| 文件 | 处理结果 |
|---|---|
| `.claude/skills/scheduled-reminder/SKILL.md` | 与来源一致。 |
| `.claude/skills/scheduled-reminder/script/__init__.py` | 与来源一致。 |
| `.claude/skills/scheduled-reminder/script/reminder.py` | 与来源一致。 |
| `.claude/skills/search-knowledge/script/search.py` | 接回统一知识库解析器，支持明确标注的文本后备。 |
| `.gitignore` | 保留原功能，并沿用已集成的账号归属、统一数据库或界面适配。 |
| `PLAN.md` | 保留原设计，开头明确旧浏览器身份方案已被账号身份替代。 |
| `agents/base_agent.py` | 补入仅咨询助手能选择/执行提醒工具的限制。 |
| `agents/consultation_agent.py` | 与来源一致。 |
| `agents/skill_registry_mixin.py` | 与来源一致。 |
| `config.py` | 补入忽略提交的 .env 兼容读取；进程及集成入口已有配置不覆盖。 |
| `constraints/agent_constraints.yaml` | 与来源一致。 |
| `constraints/swarm_constraints.yaml` | 补入提醒路由及咨询助手选择规则。 |
| `knowledge/__init__.py` | 导出完整知识库接口及小型文本检索入口。 |
| `knowledge/mini_kb.py` | 补入完整文本检索；auto/milvus/mini 可选，证据模式禁止静默降级。 |
| `messenger.py` | 功能保留，JSON路径函数 channel_path 由统一业务数据库替代。 |
| `qq/__init__.py` | 与来源一致。 |
| `qq/bridge.py` | 保留原功能，并沿用已集成的账号归属、统一数据库或界面适配。 |
| `qq/onebot.py` | 与来源一致。 |
| `qq/snowluma.py` | 与来源一致。 |
| `qq/test_bridge.py` | 保留原功能，并沿用已集成的账号归属、统一数据库或界面适配。 |
| `reminders/__init__.py` | 与来源一致。 |
| `reminders/context.py` | 与来源一致。 |
| `reminders/schedule.py` | 与来源一致。 |
| `reminders/service.py` | 保留原功能，并沿用已集成的账号归属、统一数据库或界面适配。 |
| `reminders/store.py` | 保留原功能，并沿用已集成的账号归属、统一数据库或界面适配。 |
| `requirements.txt` | 依赖经统一入口转到 requirements.integration.txt，新增依赖均已包含。 |
| `requirements.web.txt` | 依赖经统一入口转到 requirements.integration.txt，新增依赖均已包含。 |
| `run_web.py` | 保留统一启动、端口、业务库和本地配置加载，包含渠道日志。 |
| `swarm/lead_agent.py` | 保留原功能，并沿用已集成的账号归属、统一数据库或界面适配。 |
| `web/app.py` | 全部提醒/渠道业务路由保留；匿名 local_session 由现有账号鉴权中间件替代。 |
| `web/static/app.js` | 保留原功能，并沿用已集成的账号归属、统一数据库或界面适配。 |
| `web/static/index.html` | 保留原功能，并沿用已集成的账号归属、统一数据库或界面适配。 |
| `web/static/style.css` | 纳入渠道和提醒样式，并保留集成版样式。 |
| `web/test_reminders.py` | 保留调度/幂等测试；旧匿名 Cookie 测试改为账号隔离，后备检索另有专项测试。 |
| `web/test_web.py` | 保留原功能，并沿用已集成的账号归属、统一数据库或界面适配。 |
| `wechat/__init__.py` | 与来源一致。 |
| `wechat/bridge.py` | 保留原功能，并沿用已集成的账号归属、统一数据库或界面适配。 |
| `wechat/ilink.py` | 与来源一致。 |
| `wechat/qr.py` | 与来源一致。 |
| `wechat/test_bridge.py` | 保留原功能，并沿用已集成的账号归属、统一数据库或界面适配。 |

## 边界

原分支所用匿名浏览器 Cookie、独立提醒 SQLite、渠道 JSON 凭证文件不会重新引入。现有手机号鉴权、用户 ID、CSRF、账号隔离继续生效。完整 Git 合并不要求恢复已经替换掉的旧实现。

知识库新登记来源与构建脚本已纳入；第三方正文、向量索引、模型缓存和密钥仍不进 Git。本机旧样例库的180条就绪不等于新证据库的3298篇正文已下载。真实模型、Mem0、QQ/微信收发仍按独立服务联调验收。

证据专用启动入口也已与账号入口统一，保留默认8766及--prepare-only，同时加载相同本地配置。知识库来源目录分页有独立接口回归。

## 本轮验证结果

完整补合版本运行 `python scripts/verify_integration.py`：327项通过；前端全部JavaScript和变更Python模块语法检查通过。通过merge-base检查各成员固定提交均为main_copy祖先；不将真实外部服务成功计入这些离线回归。
